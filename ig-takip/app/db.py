"""Veritabanı modelleri (SQLAlchemy 2.0). SQLite ile başlar, DATABASE_URL ile Postgres'e geçer."""
from __future__ import annotations

import os
import secrets
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings

GROUPS = {
    "ekran_yuzu": "Ekran yüzü",
    "influencer": "Influencer",
    "rakip": "Rakip",
}

STATUSES = {
    "bekliyor": "Henüz toplanmadı",
    "ok": "Güncel",
    "isletme_degil": "Kişisel hesap (API dışı)",
    "baglanti_gerekli": "Bağlantı yenilenmeli",
    "yapilandirma_eksik": "API ayarı eksik",
    "hata": "Hata",
}

SOURCES = {
    "oauth": "Bağlı hesap (tam veri)",
    "discovery": "Meta API (herkese açık)",
    "apify": "Apify (herkese açık)",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    group: Mapped[str] = mapped_column(String(20), default="rakip", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Profil (son toplamadan)
    name: Mapped[str | None] = mapped_column(String(200))
    biography: Mapped[str | None] = mapped_column(Text)
    profile_picture_url: Mapped[str | None] = mapped_column(Text)
    ig_user_id: Mapped[str | None] = mapped_column(String(64))

    # Durum
    status: Mapped[str] = mapped_column(String(30), default="bekliyor")
    data_source: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime)

    # OAuth (Instagram Login)
    connect_token: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: secrets.token_urlsafe(24))
    oauth_token_enc: Mapped[str | None] = mapped_column(Text)
    oauth_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    oauth_connected_at: Mapped[datetime | None] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    snapshots: Mapped[list["AccountSnapshot"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    posts: Mapped[list["Post"]] = relationship(back_populates="account", cascade="all, delete-orphan")

    @property
    def group_label(self) -> str:
        return GROUPS.get(self.group, self.group)

    @property
    def status_label(self) -> str:
        return STATUSES.get(self.status, self.status)

    @property
    def source_label(self) -> str:
        return SOURCES.get(self.data_source or "", "—")

    @property
    def is_connected(self) -> bool:
        return bool(self.oauth_token_enc)


class AccountSnapshot(Base):
    """Bir hesabın belirli bir gündeki profil sayıları."""
    __tablename__ = "account_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "date", name="uq_account_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    followers: Mapped[int | None] = mapped_column(Integer)
    follows: Mapped[int | None] = mapped_column(Integer)
    media_count: Mapped[int | None] = mapped_column(Integer)

    account: Mapped[Account] = relationship(back_populates="snapshots")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Instagram media id
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    caption: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(30))       # IMAGE / VIDEO / CAROUSEL_ALBUM
    product_type: Mapped[str | None] = mapped_column(String(30))     # FEED / REELS / STORY
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    permalink: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Son ölçüm (hızlı listeleme için kopyası; geçmiş PostSnapshot'ta)
    likes: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    views: Mapped[int | None] = mapped_column(Integer)
    reach: Mapped[int | None] = mapped_column(Integer)
    saved: Mapped[int | None] = mapped_column(Integer)
    shares: Mapped[int | None] = mapped_column(Integer)
    engagement_rate: Mapped[float | None] = mapped_column(Float)  # (beğeni+yorum)/takipçi %

    account: Mapped[Account] = relationship(back_populates="posts")
    snapshots: Mapped[list["PostSnapshot"]] = relationship(back_populates="post", cascade="all, delete-orphan")

    @property
    def kind_label(self) -> str:
        if self.product_type == "REELS":
            return "Reels"
        if self.product_type == "STORY":
            return "Hikaye"
        return {"CAROUSEL_ALBUM": "Kaydırmalı", "VIDEO": "Video", "IMAGE": "Fotoğraf"}.get(self.media_type or "", "Gönderi")


class PostSnapshot(Base):
    __tablename__ = "post_snapshots"
    __table_args__ = (UniqueConstraint("post_id", "date", name="uq_post_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    likes: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    views: Mapped[int | None] = mapped_column(Integer)
    reach: Mapped[int | None] = mapped_column(Integer)
    saved: Mapped[int | None] = mapped_column(Integer)
    shares: Mapped[int | None] = mapped_column(Integer)

    post: Mapped[Post] = relationship(back_populates="snapshots")


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    trigger: Mapped[str] = mapped_column(String(20), default="zamanlayici")
    ok_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    log: Mapped[str] = mapped_column(Text, default="")


def _make_engine(url: str):
    if url.startswith("sqlite:///"):
        path = url.removeprefix("sqlite:///")
        if path not in ("", ":memory:"):
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    if url.startswith("postgres://"):  # Railway/Heroku tarzı URL
        url = "postgresql+psycopg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return create_engine(url, pool_pre_ping=True)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(bind=None) -> None:
    Base.metadata.create_all(bind or engine)
