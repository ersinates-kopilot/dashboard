"""Demo verisi: Meta bilgileri gelmeden dashboard'u görmek için kurgusal hesaplar üretir.

Kullanım:  python -m scripts.seed_demo        (mevcut demo_ hesaplarını silip yeniden üretir)
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from app.collector import engagement_rate
from app.config import settings
from app.db import Account, AccountSnapshot, Post, PostSnapshot, SessionLocal, init_db

DEMO = [
    # kullanıcı adı, grup, başlangıç takipçi, günlük büyüme oranı, ort. ER, bağlı mı
    ("demo_ayse_sunucu", "ekran_yuzu", 182_000, 0.0021, 4.1, True),
    ("demo_mert_tv", "ekran_yuzu", 96_500, 0.0034, 5.6, True),
    ("demo_zeynep_haber", "ekran_yuzu", 310_000, 0.0009, 2.7, True),
    ("demo_can_gezer", "influencer", 540_000, 0.0012, 3.2, True),
    ("demo_elif_mutfak", "influencer", 128_000, 0.0026, 6.3, False),
    ("demo_deniz_fit", "influencer", 74_000, 0.0041, 7.8, False),
    ("demo_rakip_medya", "rakip", 890_000, 0.0007, 1.9, False),
    ("demo_rakip_studyo", "rakip", 233_000, 0.0018, 3.4, False),
    ("demo_rakip_yildiz", "rakip", 415_000, -0.0002, 2.2, False),
]
CAPTIONS = [
    "Yeni bölüm yayında! Kaçıranlar için kısa bir özet", "Kamera arkası: bugünkü çekimden kareler",
    "Sizce hangisi? Yorumlarda buluşalım", "Haftanın en çok sorulan sorusunu yanıtladım",
    "İş birliği: yeni koleksiyonu denedik", "Sabah rutinim, 60 saniyede", "Canlı yayın tekrarından en iyi an",
    "3 ipucu: kameraya rahat konuşmak", "Bu akşam 21.00'de ekranlardayız", "Takipçi soruları #12",
]


def run(days: int = 75, seed: int = 7) -> None:
    random.seed(seed)
    init_db()
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as db:
        old = db.scalars(select(Account).where(Account.username.like("demo\\_%", escape="\\"))).all()
        for a in old:
            db.delete(a)
        db.commit()
        for i, (name, group, start, growth, er, connected) in enumerate(DEMO):
            acc = Account(username=name, group=group, name=name.removeprefix("demo_").replace("_", " ").title(),
                          status="ok", data_source="oauth" if connected else "discovery",
                          last_collected_at=now, notes="Demo hesap — silebilirsiniz",
                          oauth_token_enc="demo" if connected else None,
                          oauth_connected_at=now - timedelta(days=days) if connected else None,
                          oauth_token_expires_at=now + timedelta(days=50) if connected else None)
            db.add(acc)
            db.flush()
            f = start
            fol_by_day = {}
            for d in range(days, -1, -1):
                day = today - timedelta(days=d)
                f = int(f * (1 + growth + random.gauss(0, 0.0012)))
                if random.random() < 0.03:
                    f = int(f * 1.012)  # viral gün sıçraması
                fol_by_day[day] = f
                db.add(AccountSnapshot(account_id=acc.id, date=day, followers=f, follows=random.randint(300, 1500),
                                       media_count=400 + (days - d) // 2))
            n_posts = random.randint(days // 4, days // 2)
            for k in range(n_posts):
                posted = now - timedelta(days=random.uniform(0, days), hours=random.uniform(0, 12))
                fol = fol_by_day.get(posted.date(), f)
                reel = random.random() < 0.55
                mult = random.lognormvariate(0, 0.45) * (3.2 if random.random() < 0.06 else 1)
                likes = int(fol * er / 100 * 0.93 * mult)
                comments = int(likes * random.uniform(0.02, 0.07))
                views = int(likes * random.uniform(9, 18)) if reel else None
                p = Post(id=f"{name}_{k}", account_id=acc.id, caption=random.choice(CAPTIONS),
                         media_type="VIDEO" if reel else random.choice(["IMAGE", "CAROUSEL_ALBUM"]),
                         product_type="REELS" if reel else "FEED", posted_at=posted,
                         permalink=f"https://www.instagram.com/{name}/", likes=likes, comments=comments, views=views)
                if connected:
                    p.reach = int(fol * random.uniform(0.25, 0.6) * mult)
                    p.saved = int(likes * random.uniform(0.03, 0.12))
                    p.shares = int(likes * random.uniform(0.02, 0.09))
                p.engagement_rate = engagement_rate(likes, comments, f)
                db.add(p)
                db.add(PostSnapshot(post_id=p.id, date=today, likes=likes, comments=comments, views=views,
                                    reach=p.reach, saved=p.saved, shares=p.shares))
        db.commit()
    print(f"{len(DEMO)} demo hesap ve {days} günlük geçmiş oluşturuldu.")


if __name__ == "__main__":
    run()
