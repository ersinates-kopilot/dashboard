"""Dashboard için hesaplanan metrikler."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Account, AccountSnapshot, Post, utcnow

RECENT_POSTS = 12  # ortalama etkileşim için son N gönderi


@dataclass
class AccountSummary:
    account: Account
    followers: int | None
    change_7d: int | None
    change_7d_pct: float | None
    change_30d: int | None
    avg_er: float | None           # son 12 gönderi ortalama etkileşim %
    avg_likes: float | None
    avg_views: float | None
    avg_reach: float | None        # yalnızca bağlı hesaplar
    posts_per_week: float | None
    last_post_at: object | None


def _snapshot_on_or_before(snaps: list[AccountSnapshot], day: date) -> AccountSnapshot | None:
    best = None
    for s in snaps:  # tarih sırasına göre artan
        if s.date <= day and s.followers is not None:
            best = s
    return best


def follower_change(snaps: list[AccountSnapshot], days: int) -> tuple[int | None, float | None]:
    valid = [s for s in snaps if s.followers is not None]
    if len(valid) < 2:
        return None, None
    last = valid[-1]
    base = _snapshot_on_or_before(valid, last.date - timedelta(days=days))
    if base is None:
        base = valid[0]
    if base.date == last.date:
        return None, None
    diff = last.followers - base.followers
    pct = round(diff / base.followers * 100, 2) if base.followers else None
    return diff, pct


def summarize(db: Session, acc: Account) -> AccountSummary:
    snaps = list(db.scalars(select(AccountSnapshot).where(AccountSnapshot.account_id == acc.id)
                            .order_by(AccountSnapshot.date)))
    posts = list(db.scalars(select(Post).where(Post.account_id == acc.id)
                            .order_by(Post.posted_at.desc()).limit(RECENT_POSTS)))
    followers = next((s.followers for s in reversed(snaps) if s.followers is not None), None)
    ch7, ch7p = follower_change(snaps, 7)
    ch30, _ = follower_change(snaps, 30)

    ers = [p.engagement_rate for p in posts if p.engagement_rate is not None]
    likes = [p.likes for p in posts if p.likes is not None]
    views = [p.views for p in posts if p.views]
    reach = [p.reach for p in posts if p.reach]

    cutoff = utcnow() - timedelta(days=30)
    recent = db.scalars(select(Post.id).where(Post.account_id == acc.id, Post.posted_at >= cutoff)).all()
    ppw = round(len(recent) / 30 * 7, 1) if snaps else None

    return AccountSummary(
        account=acc, followers=followers, change_7d=ch7, change_7d_pct=ch7p, change_30d=ch30,
        avg_er=round(mean(ers), 2) if ers else None,
        avg_likes=round(mean(likes)) if likes else None,
        avg_views=round(mean(views)) if views else None,
        avg_reach=round(mean(reach)) if reach else None,
        posts_per_week=ppw,
        last_post_at=posts[0].posted_at if posts else None,
    )


def group_stats(summaries: list[AccountSummary]) -> dict:
    ers = [s.avg_er for s in summaries if s.avg_er is not None]
    fol = [s.followers for s in summaries if s.followers is not None]
    ppw = [s.posts_per_week for s in summaries if s.posts_per_week is not None]
    return {
        "count": len(summaries),
        "followers_total": sum(fol) if fol else None,
        "median_er": round(median(ers), 2) if ers else None,
        "avg_ppw": round(mean(ppw), 1) if ppw else None,
    }


def performance_multiple(db: Session, post: Post) -> float | None:
    """Gönderinin beğenisi, hesabın son gönderilerinin medyanına göre kaç kat? (viral tespiti)"""
    others = db.scalars(select(Post.likes).where(Post.account_id == post.account_id, Post.likes.is_not(None))
                        .order_by(Post.posted_at.desc()).limit(30)).all()
    if post.likes is None or len(others) < 5:
        return None
    med = median(others)
    return round(post.likes / med, 1) if med else None
