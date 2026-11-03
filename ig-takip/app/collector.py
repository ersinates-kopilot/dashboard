"""Toplama orkestrasyonu: her hesap için doğru kaynağı seçer, sonucu veritabanına yazar."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .collectors import CollectorError, CollectResult
from .collectors.apify import apify_collect
from .collectors.meta import business_discovery, oauth_collect, oauth_refresh
from .config import Settings, settings as default_settings
from .db import Account, AccountSnapshot, CollectionRun, Post, PostSnapshot, SessionLocal, utcnow
from .security import decrypt, encrypt

log = logging.getLogger("ig_takip.collector")


def today_local(cfg: Settings) -> date:
    return datetime.now(ZoneInfo(cfg.timezone)).date()


def _fetch(client: httpx.Client, acc: Account, cfg: Settings) -> CollectResult:
    """Kaynak sırası: bağlı hesap (OAuth) → Meta Business Discovery → Apify."""
    if acc.oauth_token_enc:
        token = decrypt(acc.oauth_token_enc)
        if not token:
            raise CollectorError("Kayıtlı token çözülemedi (SECRET_KEY değişmiş olabilir)", kind="baglanti_gerekli")
        # 60 günlük token'ı süresi dolmadan yenile
        if acc.oauth_token_expires_at and acc.oauth_token_expires_at - utcnow() < timedelta(days=10):
            try:
                token, exp = oauth_refresh(client, token)
                acc.oauth_token_enc, acc.oauth_token_expires_at = encrypt(token), exp
            except CollectorError as e:
                log.warning("Token yenilenemedi %s: %s", acc.username, e)
        return oauth_collect(client, token=token, version=cfg.graph_version, limit=cfg.posts_limit)

    discovery_err: CollectorError | None = None
    if cfg.discovery_enabled:
        try:
            return business_discovery(client, username=acc.username, ig_business_id=cfg.meta_ig_business_id,
                                      token=cfg.meta_system_token, version=cfg.graph_version,
                                      limit=cfg.posts_limit)
        except CollectorError as e:
            if e.kind != "isletme_degil" or not cfg.apify_enabled:
                raise
            discovery_err = e
    if cfg.apify_enabled:
        return apify_collect(client, username=acc.username, token=cfg.apify_token, actor=cfg.apify_actor)
    if discovery_err:
        raise discovery_err
    raise CollectorError("Meta API bilgileri (.env) girilmemiş", kind="yapilandirma_eksik")


def save_result(db: Session, acc: Account, res: CollectResult, day: date) -> None:
    p = res.profile
    acc.name = p.name or acc.name
    acc.biography = p.biography
    acc.profile_picture_url = p.profile_picture_url or acc.profile_picture_url
    acc.ig_user_id = p.ig_user_id or acc.ig_user_id
    acc.data_source = res.source
    acc.status, acc.last_error, acc.last_collected_at = "ok", None, utcnow()

    snap = db.scalar(select(AccountSnapshot).where(AccountSnapshot.account_id == acc.id, AccountSnapshot.date == day))
    if not snap:
        snap = AccountSnapshot(account_id=acc.id, date=day)
        db.add(snap)
    snap.followers, snap.follows, snap.media_count = p.followers, p.follows, p.media_count

    for pd in res.posts:
        post = db.get(Post, pd.id)
        if not post:
            post = Post(id=pd.id, account_id=acc.id)
            db.add(post)
        post.caption, post.media_type, post.product_type = pd.caption, pd.media_type, pd.product_type
        post.posted_at, post.permalink = pd.posted_at or post.posted_at, pd.permalink
        for f in ("likes", "comments", "views", "reach", "saved", "shares"):
            setattr(post, f, getattr(pd, f))
        post.engagement_rate = engagement_rate(pd.likes, pd.comments, p.followers)

        ps = db.scalar(select(PostSnapshot).where(PostSnapshot.post_id == pd.id, PostSnapshot.date == day))
        if not ps:
            ps = PostSnapshot(post_id=pd.id, date=day)
            db.add(ps)
        for f in ("likes", "comments", "views", "reach", "saved", "shares"):
            setattr(ps, f, getattr(pd, f))


def engagement_rate(likes: int | None, comments: int | None, followers: int | None) -> float | None:
    """Herkese açık etkileşim oranı: (beğeni + yorum) / takipçi × 100.

    Tüm gruplar için aynı formül kullanılır; böylece bağlı hesaplar ile rakipler adil
    karşılaştırılır. Beğeniler gizliyse hesaplanmaz.
    """
    if likes is None or not followers:
        return None
    return round((likes + (comments or 0)) / followers * 100, 2)


def collect_account(db: Session, acc: Account, client: httpx.Client, cfg: Settings) -> bool:
    try:
        res = _fetch(client, acc, cfg)
        save_result(db, acc, res, today_local(cfg))
        db.commit()
        return True
    except CollectorError as e:
        db.rollback()
        acc.status, acc.last_error, acc.last_collected_at = e.kind, str(e), utcnow()
        db.commit()
        return False
    except httpx.HTTPError as e:
        db.rollback()
        acc.status, acc.last_error, acc.last_collected_at = "hata", f"Ağ hatası: {e}", utcnow()
        db.commit()
        return False


def collect_all(trigger: str = "zamanlayici", cfg: Settings | None = None,
                account_ids: list[int] | None = None, client: httpx.Client | None = None) -> CollectionRun:
    cfg = cfg or default_settings
    own_client = client is None
    client = client or httpx.Client(timeout=30)
    with SessionLocal() as db:
        run = CollectionRun(trigger=trigger)
        db.add(run)
        db.commit()
        q = select(Account).where(Account.active.is_(True))
        if account_ids:
            q = q.where(Account.id.in_(account_ids))
        lines, ok_n, err_n = [], 0, 0
        accounts = [a for a in db.scalars(q).all() if not a.username.startswith("demo_")]  # demo verisi toplanmaz
        for i, acc in enumerate(accounts):
            if i and cfg.request_delay_seconds:
                time.sleep(cfg.request_delay_seconds)
            ok = collect_account(db, acc, client, cfg)
            ok_n, err_n = ok_n + ok, err_n + (not ok)  # sayaçlar yerelde; hesap hatasında rollback silmesin
            lines.append(f"{'✓' if ok else '✗'} @{acc.username}" + ("" if ok else f" — {acc.last_error}"))
        run.ok_count, run.error_count = ok_n, err_n
        run.finished_at = utcnow()
        run.log = "\n".join(lines)
        db.commit()
        log.info("Toplama bitti: %s başarılı, %s hatalı", run.ok_count, run.error_count)
    if own_client:
        client.close()
    return run
