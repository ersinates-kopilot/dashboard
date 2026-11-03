"""FastAPI uygulaması: dashboard, hesap yönetimi, Instagram bağlantı akışı ve zamanlayıcı."""
from __future__ import annotations

import logging
import re
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import metrics
from .collector import collect_all
from .collectors import CollectorError
from .collectors.meta import oauth_authorize_url, oauth_collect, oauth_exchange_code
from .config import settings
from .db import GROUPS, Account, AccountSnapshot, CollectionRun, Post, SessionLocal, init_db, utcnow
from .security import encrypt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ig_takip")
BASE_DIR = Path(__file__).parent
USERNAME_RE = re.compile(r"^[a-z0-9._]{1,30}$")

_collect_lock = threading.Lock()


def run_collection(trigger: str, account_ids: list[int] | None = None) -> None:
    if not _collect_lock.acquire(blocking=False):
        log.info("Toplama zaten çalışıyor, atlandı")
        return
    try:
        collect_all(trigger=trigger, account_ids=account_ids)
    except Exception:  # zamanlayıcı ölmesin
        log.exception("Toplama başarısız")
    finally:
        _collect_lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = None
    if settings.run_scheduler:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone=settings.timezone)
        scheduler.add_job(run_collection, CronTrigger(hour=settings.collect_hour, minute=settings.collect_minute),
                          args=["zamanlayici"], id="gunluk_toplama", max_instances=1, coalesce=True)
        scheduler.start()
        log.info("Günlük toplama %02d:%02d (%s) için planlandı", settings.collect_hour,
                 settings.collect_minute, settings.timezone)
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Instagram Takip", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, max_age=60 * 60 * 24 * 14,
                   https_only=settings.base_url.startswith("https"))
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ------------------------------------------------------------------ biçimlendirme

def _num(v, digits: int = 0):
    if v is None:
        return "—"
    s = f"{v:,.{digits}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _compact(v):
    if v is None:
        return "—"
    for div, suf in ((1_000_000, " Mn"), (1_000, " B")):
        if abs(v) >= div:
            return _num(v / div, 1).removesuffix(",0") + suf
    return _num(v)


def _signed(v, digits: int = 0):
    if v is None:
        return "—"
    return ("+" if v > 0 else "−" if v < 0 else "") + _num(abs(v), digits)


def _pct(v, digits: int = 2):
    return "—" if v is None else f"%{_num(v, digits)}"


def _local(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(settings.timezone))


def _tarih(dt, fmt="%d.%m.%Y"):
    d = _local(dt) if isinstance(dt, datetime) else dt
    return "—" if d is None else d.strftime(fmt)


def _ago(dt):
    if dt is None:
        return "—"
    days = (utcnow() - dt).days
    return "bugün" if days <= 0 else "dün" if days == 1 else f"{days} gün önce"


templates.env.filters.update(num=_num, compact=_compact, signed=_signed, pct=_pct, tarih=_tarih, ago=_ago)
templates.env.globals.update(GROUPS=GROUPS, settings=settings)


# ------------------------------------------------------------------ yardımcılar

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class NotAuthenticated(Exception):
    pass


@app.exception_handler(NotAuthenticated)
async def _redirect_login(request: Request, exc: NotAuthenticated):
    return RedirectResponse(f"/giris?next={request.url.path}", status_code=303)


def require_login(request: Request):
    if not request.session.get("auth"):
        raise NotAuthenticated()


def render(request: Request, name: str, **ctx):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, name, {"flash": flash, "active_nav": ctx.pop("nav", ""), **ctx})


def flash(request: Request, msg: str, kind: str = "ok"):
    request.session["flash"] = {"msg": msg, "kind": kind}


def _group_filter(grup: str | None) -> str | None:
    return grup if grup in GROUPS else None


# ------------------------------------------------------------------ giriş

@app.get("/giris", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    return render(request, "login.html", next=next)


@app.post("/giris")
def login(request: Request, password: str = Form(...), next: str = Form("/")):
    if secrets.compare_digest(password, settings.admin_password):
        request.session["auth"] = True
        return RedirectResponse(next if next.startswith("/") else "/", status_code=303)
    flash(request, "Şifre hatalı", "hata")
    return RedirectResponse("/giris", status_code=303)


@app.get("/cikis")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/giris", status_code=303)


@app.get("/saglik")
def health():
    return {"durum": "ok"}


# ------------------------------------------------------------------ dashboard

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def overview(request: Request, grup: str | None = None, db: Session = Depends(get_db)):
    grup = _group_filter(grup)
    q = select(Account).where(Account.active.is_(True)).order_by(Account.username)
    accounts = db.scalars(q).all()
    summaries = [metrics.summarize(db, a) for a in accounts]
    by_group = {g: [s for s in summaries if s.account.group == g] for g in GROUPS}
    stats = {g: metrics.group_stats(v) for g, v in by_group.items()}
    rows = [s for s in summaries if not grup or s.account.group == grup]
    rows.sort(key=lambda s: s.followers or 0, reverse=True)

    since = utcnow() - timedelta(days=7)
    top_q = (select(Post).join(Account).where(Account.active.is_(True), Post.posted_at >= since,
                                               Post.engagement_rate.is_not(None))
             .order_by(Post.engagement_rate.desc()).limit(8))
    if grup:
        top_q = top_q.where(Account.group == grup)
    top_posts = db.scalars(top_q).all()

    last_run = db.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
    problems = [a for a in accounts if a.status not in ("ok", "bekliyor")]
    return render(request, "overview.html", nav="genel", grup=grup, rows=rows, stats=stats,
                  top_posts=top_posts, last_run=last_run, problems=problems)


@app.get("/hesap/{account_id}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def account_detail(request: Request, account_id: int, sirala: str = "tarih", db: Session = Depends(get_db)):
    acc = db.get(Account, account_id) or _404()
    summary = metrics.summarize(db, acc)
    snaps = db.scalars(select(AccountSnapshot).where(AccountSnapshot.account_id == acc.id)
                       .order_by(AccountSnapshot.date)).all()
    order = {"er": Post.engagement_rate.desc().nulls_last(), "begeni": Post.likes.desc().nulls_last(),
             "izlenme": Post.views.desc().nulls_last()}.get(sirala, Post.posted_at.desc())
    posts = db.scalars(select(Post).where(Post.account_id == acc.id).order_by(order).limit(60)).all()
    multiples = {p.id: metrics.performance_multiple(db, p) for p in posts}
    chrono = sorted([p for p in posts if p.posted_at], key=lambda p: p.posted_at)[-30:]
    chart = {
        "followers": {"labels": [s.date.strftime("%d.%m") for s in snaps if s.followers is not None],
                      "values": [s.followers for s in snaps if s.followers is not None]},
        "er": {"labels": [_tarih(p.posted_at, "%d.%m") for p in chrono],
               "values": [p.engagement_rate for p in chrono],
               "captions": [(p.caption or "")[:60] for p in chrono]},
    }
    has_insights = any(p.reach is not None for p in posts)
    return render(request, "account.html", nav="", acc=acc, s=summary, posts=posts, chart=chart,
                  multiples=multiples, sirala=sirala, has_insights=has_insights,
                  connect_url=f"{settings.base_url}/baglan/{acc.connect_token}")


@app.get("/icerikler", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def contents(request: Request, grup: str | None = None, gun: int = 30, sirala: str = "er",
             tur: str | None = None, db: Session = Depends(get_db)):
    grup = _group_filter(grup)
    gun = gun if gun in (7, 30, 90) else 30
    order = {"er": Post.engagement_rate.desc().nulls_last(), "begeni": Post.likes.desc().nulls_last(),
             "yorum": Post.comments.desc().nulls_last(), "izlenme": Post.views.desc().nulls_last(),
             "tarih": Post.posted_at.desc()}.get(sirala, Post.engagement_rate.desc().nulls_last())
    q = (select(Post).join(Account).where(Account.active.is_(True), Post.posted_at >= utcnow() - timedelta(days=gun))
         .order_by(order).limit(200))
    if grup:
        q = q.where(Account.group == grup)
    if tur == "reels":
        q = q.where(Post.product_type == "REELS")
    elif tur == "gonderi":
        q = q.where(Post.product_type != "REELS")
    posts = db.scalars(q).all()
    return render(request, "contents.html", nav="icerik", posts=posts, grup=grup, gun=gun, sirala=sirala, tur=tur)


@app.get("/karsilastir", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def compare(request: Request, ids: str = "", gun: int = 30, db: Session = Depends(get_db)):
    all_accounts = db.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.group, Account.username)).all()
    selected_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()][:8]
    selected = [a for a in all_accounts if a.id in selected_ids]
    selected.sort(key=lambda a: selected_ids.index(a.id))
    gun = gun if gun in (30, 90, 180) else 30
    start = (datetime.now(ZoneInfo(settings.timezone)) - timedelta(days=gun)).date()
    series, summaries = [], []
    for a in selected:
        snaps = db.scalars(select(AccountSnapshot).where(AccountSnapshot.account_id == a.id,
                                                         AccountSnapshot.date >= start,
                                                         AccountSnapshot.followers.is_not(None))
                           .order_by(AccountSnapshot.date)).all()
        base = snaps[0].followers if snaps else None
        series.append({
            "name": "@" + a.username,
            "points": [{"x": s.date.isoformat(), "y": round((s.followers / base - 1) * 100, 2) if base else None,
                        "raw": s.followers} for s in snaps],
        })
        summaries.append(metrics.summarize(db, a))
    return render(request, "compare.html", nav="karsilastir", all_accounts=all_accounts, selected=selected,
                  selected_ids=selected_ids, series=series, summaries=summaries, gun=gun)


# ------------------------------------------------------------------ hesap yönetimi

@app.get("/hesaplar", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def accounts_page(request: Request, db: Session = Depends(get_db)):
    accounts = db.scalars(select(Account).order_by(Account.group, Account.username)).all()
    runs = db.scalars(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(5)).all()
    return render(request, "accounts.html", nav="hesaplar", accounts=accounts, runs=runs,
                  running=_collect_lock.locked())


def _parse_usernames(raw: str) -> list[str]:
    out = []
    for tok in re.split(r"[\s,;]+", raw):
        tok = tok.strip().lower().lstrip("@")
        m = re.search(r"instagram\.com/([a-z0-9._]+)", tok)
        if m:
            tok = m.group(1)
        if tok and USERNAME_RE.match(tok) and tok not in out:
            out.append(tok)
    return out


@app.post("/hesaplar/ekle", dependencies=[Depends(require_login)])
def add_accounts(request: Request, usernames: str = Form(...), group: str = Form(...), db: Session = Depends(get_db)):
    if group not in GROUPS:
        raise HTTPException(400, "Geçersiz grup")
    names = _parse_usernames(usernames)
    added, skipped = [], []
    existing = set(db.scalars(select(Account.username).where(Account.username.in_(names))).all())
    for n in names:
        if n in existing:
            skipped.append(n)
            continue
        db.add(Account(username=n, group=group))
        added.append(n)
    db.commit()
    msg = f"{len(added)} hesap eklendi."
    if skipped:
        msg += f" Zaten listede: {', '.join('@' + s for s in skipped)}."
    flash(request, msg if names else "Geçerli kullanıcı adı bulunamadı", "ok" if added else "hata")
    return RedirectResponse("/hesaplar", status_code=303)


@app.post("/hesaplar/{account_id}/guncelle", dependencies=[Depends(require_login)])
def update_account(request: Request, account_id: int, group: str = Form(...), notes: str = Form(""),
                   active: str | None = Form(None), db: Session = Depends(get_db)):
    acc = db.get(Account, account_id) or _404()
    if group in GROUPS:
        acc.group = group
    acc.notes, acc.active = notes.strip(), active == "on"
    db.commit()
    flash(request, f"@{acc.username} güncellendi")
    return RedirectResponse(request.headers.get("referer") or "/hesaplar", status_code=303)


@app.post("/hesaplar/{account_id}/sil", dependencies=[Depends(require_login)])
def delete_account(request: Request, account_id: int, db: Session = Depends(get_db)):
    acc = db.get(Account, account_id) or _404()
    db.delete(acc)
    db.commit()
    flash(request, f"@{acc.username} ve tüm geçmiş verisi silindi")
    return RedirectResponse("/hesaplar", status_code=303)


@app.post("/hesaplar/{account_id}/baglanti-kaldir", dependencies=[Depends(require_login)])
def disconnect_account(request: Request, account_id: int, db: Session = Depends(get_db)):
    acc = db.get(Account, account_id) or _404()
    acc.oauth_token_enc = acc.oauth_token_expires_at = acc.oauth_connected_at = None
    acc.connect_token = secrets.token_urlsafe(24)  # eski link de geçersiz olur
    db.commit()
    flash(request, f"@{acc.username} bağlantısı kaldırıldı")
    return RedirectResponse(f"/hesap/{acc.id}", status_code=303)


@app.post("/topla", dependencies=[Depends(require_login)])
def trigger_collect(request: Request, account_id: int | None = Form(None)):
    if _collect_lock.locked():
        flash(request, "Toplama zaten çalışıyor; birkaç dakika sonra sayfayı yenileyin", "hata")
    else:
        ids = [account_id] if account_id else None
        threading.Thread(target=run_collection, args=("elle", ids), daemon=True).start()
        flash(request, "Veri toplama başladı. Hesap sayısına göre birkaç dakika sürebilir.")
    return RedirectResponse(request.headers.get("referer") or "/hesaplar", status_code=303)


# ------------------------------------------------------------------ Instagram bağlantısı (OAuth)

@app.get("/baglan/{connect_token}", response_class=HTMLResponse)
def connect_page(request: Request, connect_token: str, db: Session = Depends(get_db)):
    acc = db.scalar(select(Account).where(Account.connect_token == connect_token))
    if not acc:
        return render(request, "connect.html", acc=None, error="Bu bağlantı linki geçersiz veya yenilenmiş.")
    if not settings.oauth_enabled:
        return render(request, "connect.html", acc=acc, error="Instagram bağlantısı henüz yapılandırılmadı.")
    request.session["oauth_state"] = connect_token
    url = oauth_authorize_url(settings.ig_app_id, settings.oauth_redirect_uri, connect_token)
    return render(request, "connect.html", acc=acc, auth_url=url, error=None)


@app.get("/oauth/instagram/callback", response_class=HTMLResponse)
def oauth_callback(request: Request, state: str = "", code: str | None = None, error: str | None = None,
                   db: Session = Depends(get_db)):
    acc = db.scalar(select(Account).where(Account.connect_token == state)) if state else None
    if not acc:
        return render(request, "connect.html", acc=None, error="Geçersiz bağlantı isteği.")
    if error or not code:
        return render(request, "connect.html", acc=acc, error="İzin verilmedi. Dilerseniz tekrar deneyebilirsiniz.")
    try:
        with httpx.Client(timeout=30) as client:
            token, expires = oauth_exchange_code(client, app_id=settings.ig_app_id, app_secret=settings.ig_app_secret,
                                                 redirect_uri=settings.oauth_redirect_uri, code=code.removesuffix("#_"))
            me = oauth_collect(client, token=token, version=settings.graph_version, limit=1, with_insights=False)
    except (CollectorError, httpx.HTTPError) as e:
        log.warning("OAuth başarısız %s: %s", acc.username, e)
        return render(request, "connect.html", acc=acc, error=f"Bağlantı tamamlanamadı: {e}")
    if me.profile.username.lower() != acc.username.lower():
        return render(request, "connect.html", acc=acc,
                      error=f"Instagram'da @{me.profile.username} hesabıyla giriş yaptınız, ancak bu link "
                            f"@{acc.username} için. Doğru hesapla tekrar deneyin.")
    acc.oauth_token_enc, acc.oauth_token_expires_at, acc.oauth_connected_at = encrypt(token), expires, utcnow()
    acc.status = "bekliyor"
    db.commit()
    threading.Thread(target=run_collection, args=("baglanti", [acc.id]), daemon=True).start()
    return render(request, "connect.html", acc=acc, success=True, error=None)


@app.get("/api/durum", dependencies=[Depends(require_login)])
def api_status(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Account.status, func.count()).group_by(Account.status)).all())
    return JSONResponse({"toplama_calisiyor": _collect_lock.locked(), "durumlar": counts})


def _404():
    raise HTTPException(404, "Bulunamadı")
