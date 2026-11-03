"""Testler: Meta yanıtları sahte (mock) HTTP ile taklit edilir; gerçek API'ye istek gitmez."""
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite:///{_tmp}/test.db", RUN_SCHEDULER="0", ADMIN_PASSWORD="test",
                  META_IG_BUSINESS_ID="1784000", META_SYSTEM_TOKEN="sys", IG_APP_ID="app", IG_APP_SECRET="sec",
                  SECRET_KEY="test-secret", REQUEST_DELAY_SECONDS="0")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.collector import collect_all, engagement_rate  # noqa: E402
from app.collectors import parse_ts  # noqa: E402
from app.collectors.meta import business_discovery, oauth_authorize_url  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import Account, AccountSnapshot, Post, SessionLocal, init_db  # noqa: E402
from app.main import _parse_usernames, app  # noqa: E402
from app.security import decrypt, encrypt  # noqa: E402

init_db()

BD_OK = {
    "business_discovery": {
        "id": "178414", "username": "rakip_marka", "name": "Rakip Marka", "followers_count": 10000,
        "follows_count": 120, "media_count": 340, "biography": "bio",
        "media": {"data": [
            {"id": "m1", "caption": "Reel", "media_type": "VIDEO", "media_product_type": "REELS",
             "timestamp": "2026-11-01T10:00:00+0000", "permalink": "https://instagram.com/p/m1",
             "like_count": 450, "comments_count": 50},
            {"id": "m2", "caption": "Gizli beğeni", "media_type": "IMAGE", "media_product_type": "FEED",
             "timestamp": "2026-10-30T08:00:00+0000", "permalink": "https://instagram.com/p/m2", "comments_count": 5},
        ]},
    },
    "id": "1784000",
}
BD_NOT_BUSINESS = {"error": {"message": "Invalid user id", "code": 110, "error_subcode": 2207013}}

IG_ME = {"user_id": "999", "username": "ekran_yuzu1", "followers_count": 5000, "follows_count": 10, "media_count": 20}
IG_MEDIA = {"data": [{"id": "x1", "media_type": "VIDEO", "media_product_type": "REELS",
                      "timestamp": "2026-11-02T09:00:00+0000", "like_count": 300, "comments_count": 20}]}
IG_INSIGHTS = {"data": [{"name": "reach", "values": [{"value": 2500}]}, {"name": "saved", "values": [{"value": 40}]},
                        {"name": "shares", "values": [{"value": 12}]}, {"name": "views", "values": [{"value": 9000}]}]}


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "graph.facebook.com" in url:
        if "username(kisisel_hesap)" in request.url.params.get("fields", ""):
            return httpx.Response(400, json=BD_NOT_BUSINESS)
        return httpx.Response(200, json=BD_OK)
    if "graph.instagram.com" in url:
        if "/insights" in url:
            return httpx.Response(200, json=IG_INSIGHTS)
        if "/me/media" in url:
            return httpx.Response(200, json=IG_MEDIA)
        if "/me" in url:
            return httpx.Response(200, json=IG_ME)
    return httpx.Response(404, json={"error": {"message": "bilinmeyen", "code": 1}})


@pytest.fixture
def mock_client():
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_ts_converts_to_utc():
    assert parse_ts("2026-11-01T13:00:00+0300").hour == 10
    assert parse_ts("2026-11-01T10:00:00.000Z").hour == 10
    assert parse_ts(None) is None


def test_engagement_rate():
    assert engagement_rate(450, 50, 10000) == 5.0
    assert engagement_rate(None, 5, 10000) is None
    assert engagement_rate(10, 0, 0) is None


def test_business_discovery_parsing(mock_client):
    res = business_discovery(mock_client, username="rakip_marka", ig_business_id="1784000", token="t", version="v24.0")
    assert res.profile.followers == 10000
    assert [p.id for p in res.posts] == ["m1", "m2"]
    assert res.posts[1].likes is None  # gizli beğeni


def test_encrypt_roundtrip():
    assert decrypt(encrypt("gizli")) == "gizli"
    assert decrypt("bozuk") is None


def test_parse_usernames():
    raw = "@Ayse.Tv, https://www.instagram.com/mert_tv/?hl=tr\nayse.tv  gecersiz-ad!"
    assert _parse_usernames(raw) == ["ayse.tv", "mert_tv"]


def test_oauth_url_contains_scopes():
    url = oauth_authorize_url("app", "https://x/cb", "st")
    assert "instagram_business_manage_insights" in url and "state=st" in url


def test_full_collection_flow(mock_client):
    with SessionLocal() as db:
        db.add_all([Account(username="rakip_marka", group="rakip"),
                    Account(username="kisisel_hesap", group="influencer"),
                    Account(username="ekran_yuzu1", group="ekran_yuzu", oauth_token_enc=encrypt("tok"))])
        db.commit()
    run = collect_all(trigger="test", cfg=Settings(), client=mock_client)
    assert run.ok_count == 2 and run.error_count == 1
    with SessionLocal() as db:
        accs = {a.username: a for a in db.query(Account)}
        assert accs["rakip_marka"].status == "ok" and accs["rakip_marka"].data_source == "discovery"
        assert accs["kisisel_hesap"].status == "isletme_degil"
        assert accs["ekran_yuzu1"].data_source == "oauth"
        p = db.get(Post, "x1")
        assert (p.reach, p.saved, p.shares, p.views) == (2500, 40, 12, 9000)
        assert db.get(Post, "m1").engagement_rate == 5.0
        assert db.query(AccountSnapshot).count() == 2
    # aynı gün tekrar toplama yeni satır açmaz
    collect_all(trigger="test", cfg=Settings(), client=mock_client)
    with SessionLocal() as db:
        assert db.query(AccountSnapshot).count() == 2


def test_pages_require_login_and_render():
    c = TestClient(app)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and "/giris" in r.headers["location"]
    assert c.post("/giris", data={"password": "yanlis"}, follow_redirects=False).headers["location"] == "/giris"
    c.post("/giris", data={"password": "test", "next": "/"})
    for url in ["/", "/icerikler", "/karsilastir?ids=1,2", "/hesaplar", "/hesap/1", "/icerikler?grup=rakip&gun=7&tur=reels"]:
        assert c.get(url).status_code == 200, url
    r = c.post("/hesaplar/ekle", data={"usernames": "yeni_hesap\nrakip_marka", "group": "rakip"})
    assert "1 hesap eklendi" in r.text and "Zaten listede" in r.text


def test_connect_page_is_public():
    with SessionLocal() as db:
        token = db.query(Account).filter_by(username="kisisel_hesap").one().connect_token
    c = TestClient(app)
    r = c.get(f"/baglan/{token}")
    assert r.status_code == 200 and "instagram.com/oauth/authorize" in r.text
    assert "geçersiz" in c.get("/baglan/yok").text
