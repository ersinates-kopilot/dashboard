"""Veri kaynaklarından gelen ham veriyi ortak bir biçime çeviren toplayıcılar."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ProfileData:
    username: str
    followers: int | None = None
    follows: int | None = None
    media_count: int | None = None
    name: str | None = None
    biography: str | None = None
    profile_picture_url: str | None = None
    ig_user_id: str | None = None


@dataclass
class PostData:
    id: str
    posted_at: datetime | None = None
    caption: str | None = None
    media_type: str | None = None
    product_type: str | None = None
    permalink: str | None = None
    likes: int | None = None
    comments: int | None = None
    views: int | None = None
    reach: int | None = None
    saved: int | None = None
    shares: int | None = None


@dataclass
class CollectResult:
    profile: ProfileData
    posts: list[PostData] = field(default_factory=list)
    source: str = ""


class CollectorError(Exception):
    """Toplama hatası. `kind` arayüzde gösterilecek durumu belirler."""

    def __init__(self, message: str, kind: str = "hata"):
        super().__init__(message)
        self.kind = kind  # hata / isletme_degil / baglanti_gerekli / yapilandirma_eksik


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    # Meta: 2026-10-30T14:05:11+0000   Apify: 2026-10-30T14:05:11.000Z
    v = value.replace("Z", "+00:00")
    if len(v) >= 5 and v[-5] in "+-" and v[-3] != ":":
        v = v[:-2] + ":" + v[-2:]
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)  # UTC olarak saklanır
    return dt
