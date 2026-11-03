"""Uygulama ayarları. Tüm değerler ortam değişkenlerinden (.env) okunur."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "evet", "yes", "on"}


@dataclass
class Settings:
    # Genel
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", "degistir-beni-uzun-rastgele-bir-anahtar"))
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", "admin"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./data/ig_takip.db"))
    base_url: str = field(default_factory=lambda: os.getenv("BASE_URL", "http://localhost:8000").rstrip("/"))
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Europe/Istanbul"))

    # Zamanlayıcı
    run_scheduler: bool = field(default_factory=lambda: _bool("RUN_SCHEDULER", True))
    collect_hour: int = field(default_factory=lambda: int(os.getenv("COLLECT_HOUR", "9")))
    collect_minute: int = field(default_factory=lambda: int(os.getenv("COLLECT_MINUTE", "17")))
    request_delay_seconds: float = field(default_factory=lambda: float(os.getenv("REQUEST_DELAY_SECONDS", "1.5")))
    posts_limit: int = field(default_factory=lambda: int(os.getenv("POSTS_LIMIT", "25")))

    # Meta Graph API (Business Discovery — rakipler ve bağlanmamış hesaplar)
    graph_version: str = field(default_factory=lambda: os.getenv("META_GRAPH_VERSION", "v24.0"))
    meta_ig_business_id: str = field(default_factory=lambda: os.getenv("META_IG_BUSINESS_ID", ""))
    meta_system_token: str = field(default_factory=lambda: os.getenv("META_SYSTEM_TOKEN", ""))

    # Instagram Login (OAuth — ekran yüzleri ve bağlanan influencerlar)
    ig_app_id: str = field(default_factory=lambda: os.getenv("IG_APP_ID", ""))
    ig_app_secret: str = field(default_factory=lambda: os.getenv("IG_APP_SECRET", ""))

    # Apify (isteğe bağlı — kişisel hesaplar için)
    apify_token: str = field(default_factory=lambda: os.getenv("APIFY_TOKEN", ""))
    apify_actor: str = field(default_factory=lambda: os.getenv("APIFY_ACTOR", "apify~instagram-profile-scraper"))

    @property
    def discovery_enabled(self) -> bool:
        return bool(self.meta_ig_business_id and self.meta_system_token)

    @property
    def oauth_enabled(self) -> bool:
        return bool(self.ig_app_id and self.ig_app_secret)

    @property
    def apify_enabled(self) -> bool:
        return bool(self.apify_token)

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.base_url}/oauth/instagram/callback"


settings = Settings()
