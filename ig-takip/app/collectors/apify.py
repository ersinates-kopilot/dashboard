"""Apify toplayıcısı (isteğe bağlı). Meta API'nin kapsamadığı kişisel hesaplar için.

Not: Bu yöntem Instagram'ın herkese açık sayfalarını tarar; Instagram kullanım şartları
açısından gri alandadır. Yalnızca APIFY_TOKEN tanımlıysa ve Meta API hesabı bulamadığında
devreye girer.
"""
from __future__ import annotations

import httpx

from . import CollectorError, CollectResult, PostData, ProfileData, parse_ts

APIFY_BASE = "https://api.apify.com/v2"

_TYPE_MAP = {"Image": "IMAGE", "Video": "VIDEO", "Sidecar": "CAROUSEL_ALBUM"}


def apify_collect(client: httpx.Client, *, username: str, token: str, actor: str) -> CollectResult:
    resp = client.post(
        f"{APIFY_BASE}/acts/{actor}/run-sync-get-dataset-items",
        params={"token": token},
        json={"usernames": [username]},
        timeout=180,
    )
    if resp.status_code >= 400:
        raise CollectorError(f"Apify hatası (HTTP {resp.status_code}): {resp.text[:200]}")
    items = resp.json()
    if not items or items[0].get("error"):
        raise CollectorError(f"Apify hesabı bulamadı: {username}")
    it = items[0]
    if it.get("private"):
        raise CollectorError("Hesap gizli; içerikleri görülemiyor", kind="isletme_degil")
    profile = ProfileData(
        username=it.get("username", username),
        followers=it.get("followersCount"),
        follows=it.get("followsCount"),
        media_count=it.get("postsCount"),
        name=it.get("fullName"),
        biography=it.get("biography"),
        profile_picture_url=it.get("profilePicUrl"),
        ig_user_id=str(it.get("id")) if it.get("id") else None,
    )
    posts = []
    for p in it.get("latestPosts") or []:
        is_reel = p.get("productType") == "clips"
        likes = p.get("likesCount")
        posts.append(PostData(
            id=str(p.get("id") or p.get("shortCode")),
            posted_at=parse_ts(p.get("timestamp")),
            caption=p.get("caption"),
            media_type=_TYPE_MAP.get(p.get("type"), p.get("type")),
            product_type="REELS" if is_reel else "FEED",
            permalink=p.get("url"),
            likes=likes if isinstance(likes, int) and likes >= 0 else None,  # gizli beğeni: -1
            comments=p.get("commentsCount"),
            views=p.get("videoPlayCount") or p.get("videoViewCount"),
        ))
    return CollectResult(profile=profile, posts=posts, source="apify")
