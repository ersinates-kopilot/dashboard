"""Meta toplayıcıları.

1) Business Discovery (graph.facebook.com): Sizin İşletme hesabınız üzerinden başka
   İşletme/İçerik Üreticisi hesaplarının herkese açık verisi. Kişisel hesaplar dönmez.
2) Instagram Login (graph.instagram.com): Hesabını bağlayan kişinin kendi verisi,
   erişim/kaydetme/paylaşım gibi istatistikler dahil.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from . import CollectorError, CollectResult, PostData, ProfileData, parse_ts

FB_GRAPH = "https://graph.facebook.com"
IG_GRAPH = "https://graph.instagram.com"
IG_OAUTH_AUTHORIZE = "https://www.instagram.com/oauth/authorize"
IG_OAUTH_TOKEN = "https://api.instagram.com/oauth/access_token"

MEDIA_FIELDS = "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count"
OAUTH_SCOPES = "instagram_business_basic,instagram_business_manage_insights"


def _raise_for_meta_error(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise CollectorError(f"Meta beklenmeyen yanıt verdi (HTTP {resp.status_code})")
    err = data.get("error") if isinstance(data, dict) else None
    if err or resp.status_code >= 400:
        err = err or {}
        code = err.get("code")
        sub = err.get("error_subcode")
        msg = err.get("error_user_msg") or err.get("message") or f"HTTP {resp.status_code}"
        if code == 190:  # token geçersiz / süresi dolmuş
            raise CollectorError(f"Erişim anahtarı geçersiz: {msg}", kind="baglanti_gerekli")
        if code == 110 or sub == 2207013 or "Cannot find User" in msg:
            raise CollectorError("Hesap bulunamadı veya İşletme/İçerik Üreticisi hesabı değil", kind="isletme_degil")
        if code in (4, 17, 32, 613):
            raise CollectorError(f"Meta istek sınırına takıldı, sonra tekrar denenecek: {msg}")
        raise CollectorError(f"Meta hatası ({code}/{sub}): {msg}")
    return data


def _post_from_media(m: dict) -> PostData:
    return PostData(
        id=str(m["id"]),
        posted_at=parse_ts(m.get("timestamp")),
        caption=m.get("caption"),
        media_type=m.get("media_type"),
        product_type=m.get("media_product_type"),
        permalink=m.get("permalink"),
        likes=m.get("like_count"),         # sahibi beğenileri gizlediyse gelmez
        comments=m.get("comments_count"),
    )


# ---------------------------------------------------------------- Business Discovery

def business_discovery(client: httpx.Client, *, username: str, ig_business_id: str, token: str,
                       version: str, limit: int = 25) -> CollectResult:
    fields = (
        f"business_discovery.username({username})"
        f"{{username,name,biography,profile_picture_url,followers_count,follows_count,media_count,"
        f"media.limit({limit}){{{MEDIA_FIELDS}}}}}"
    )
    resp = client.get(f"{FB_GRAPH}/{version}/{ig_business_id}",
                      params={"fields": fields, "access_token": token})
    data = _raise_for_meta_error(resp)
    bd = data.get("business_discovery")
    if not bd:
        raise CollectorError("Hesap bulunamadı veya İşletme/İçerik Üreticisi hesabı değil", kind="isletme_degil")
    profile = ProfileData(
        username=bd.get("username", username),
        followers=bd.get("followers_count"),
        follows=bd.get("follows_count"),
        media_count=bd.get("media_count"),
        name=bd.get("name"),
        biography=bd.get("biography"),
        profile_picture_url=bd.get("profile_picture_url"),
        ig_user_id=str(bd["id"]) if bd.get("id") else None,
    )
    posts = [_post_from_media(m) for m in (bd.get("media") or {}).get("data", [])]
    return CollectResult(profile=profile, posts=posts, source="discovery")


# ---------------------------------------------------------------- Instagram Login (OAuth)

def oauth_authorize_url(app_id: str, redirect_uri: str, state: str) -> str:
    q = urlencode({
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": OAUTH_SCOPES,
        "state": state,
        "enable_fb_login": "0",
        "force_authentication": "1",
    })
    return f"{IG_OAUTH_AUTHORIZE}?{q}"


def oauth_exchange_code(client: httpx.Client, *, app_id: str, app_secret: str, redirect_uri: str,
                        code: str) -> tuple[str, datetime]:
    """Kodu önce kısa ömürlü, sonra 60 günlük token'a çevirir."""
    resp = client.post(IG_OAUTH_TOKEN, data={
        "client_id": app_id, "client_secret": app_secret, "grant_type": "authorization_code",
        "redirect_uri": redirect_uri, "code": code,
    })
    data = _raise_for_meta_error(resp)
    if "data" in data and isinstance(data["data"], list) and data["data"]:
        data = data["data"][0]
    short = data.get("access_token")
    if not short:
        raise CollectorError("Instagram token vermedi")
    resp = client.get(f"{IG_GRAPH}/access_token", params={
        "grant_type": "ig_exchange_token", "client_secret": app_secret, "access_token": short,
    })
    data = _raise_for_meta_error(resp)
    return data["access_token"], datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=int(data.get("expires_in", 5184000)))


def oauth_refresh(client: httpx.Client, token: str) -> tuple[str, datetime]:
    resp = client.get(f"{IG_GRAPH}/refresh_access_token",
                      params={"grant_type": "ig_refresh_token", "access_token": token})
    data = _raise_for_meta_error(resp)
    return data["access_token"], datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=int(data.get("expires_in", 5184000)))


def _media_insights(client: httpx.Client, version: str, token: str, media_id: str, product_type: str | None) -> dict:
    """Gönderi istatistikleri. Bazı metrikler bazı türlerde desteklenmez; o zaman daha dar bir set denenir."""
    metric_sets = [["reach", "saved", "shares", "views"], ["reach", "saved"]]
    if product_type == "STORY":
        metric_sets = [["reach", "shares", "views"], ["reach"]]
    for metrics in metric_sets:
        resp = client.get(f"{IG_GRAPH}/{version}/{media_id}/insights",
                          params={"metric": ",".join(metrics), "access_token": token})
        try:
            data = _raise_for_meta_error(resp)
        except CollectorError as e:
            if e.kind == "baglanti_gerekli":
                raise
            continue
        out: dict[str, int] = {}
        for item in data.get("data", []):
            val = None
            if item.get("values"):
                val = item["values"][0].get("value")
            elif item.get("total_value"):
                val = item["total_value"].get("value")
            if isinstance(val, (int, float)):
                out[item["name"]] = int(val)
        return out
    return {}


def oauth_collect(client: httpx.Client, *, token: str, version: str, limit: int = 25,
                  with_insights: bool = True) -> CollectResult:
    resp = client.get(f"{IG_GRAPH}/{version}/me", params={
        "fields": "user_id,username,name,biography,profile_picture_url,followers_count,follows_count,media_count",
        "access_token": token,
    })
    me = _raise_for_meta_error(resp)
    profile = ProfileData(
        username=me.get("username", ""),
        followers=me.get("followers_count"),
        follows=me.get("follows_count"),
        media_count=me.get("media_count"),
        name=me.get("name"),
        biography=me.get("biography"),
        profile_picture_url=me.get("profile_picture_url"),
        ig_user_id=str(me.get("user_id") or me.get("id") or ""),
    )
    resp = client.get(f"{IG_GRAPH}/{version}/me/media",
                      params={"fields": MEDIA_FIELDS, "limit": limit, "access_token": token})
    media = _raise_for_meta_error(resp).get("data", [])
    posts = []
    for m in media:
        p = _post_from_media(m)
        if with_insights:
            ins = _media_insights(client, version, token, p.id, p.product_type)
            p.reach, p.saved, p.shares, p.views = ins.get("reach"), ins.get("saved"), ins.get("shares"), ins.get("views")
        posts.append(p)
    return CollectResult(profile=profile, posts=posts, source="oauth")
