import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.models.enums import QueueState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class QueueItem(Base):
    __tablename__ = "queue_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title_id: Mapped[str] = mapped_column(String(32), index=True)
    region: Mapped[str] = mapped_column(String(16), default="ALL")
    preferred_mode: Mapped[str] = mapped_column(String(16), default="direct")
    state: Mapped[str] = mapped_column(String(32), default=QueueState.QUEUED.value, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    catalog_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    queue_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("queue_items.id"), index=True)
    phase: Mapped[str] = mapped_column(String(64), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[str] = mapped_column(String(32), default="RUNNING", index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnostics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DiskAttachment(Base):
    __tablename__ = "disk_attachment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_path: Mapped[str] = mapped_column(String(256), index=True)
    wfs_fingerprint: Mapped[str] = mapped_column(String(128))
    key_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    wfs_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    attached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    detached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text)

