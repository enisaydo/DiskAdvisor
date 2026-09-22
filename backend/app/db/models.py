"""SQLAlchemy ORM models matching the schema defined in the approved plan."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    BigInteger,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hostname: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    dt_entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    disk_metrics: Mapped[list["DiskMetric"]] = relationship(back_populates="host")
    directory_audits: Mapped[list["DirectoryAudit"]] = relationship(back_populates="host")


class DiskMetric(Base):
    """Filled periodically by the collector from Dynatrace Metrics API v2."""

    __tablename__ = "disk_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id"), nullable=False, index=True)
    mount_point: Mapped[str] = mapped_column(String(255), nullable=False)
    capacity_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used_pct: Mapped[float] = mapped_column(Float, nullable=False)
    collected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    host: Mapped["Host"] = relationship(back_populates="disk_metrics")


class DirectoryAudit(Base):
    """Result of a one-time SSH/Ansible audit, cached with a TTL."""

    __tablename__ = "directory_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id"), nullable=False, index=True)
    mount_point: Mapped[str] = mapped_column(String(255), nullable=False)
    top_dirs_json: Mapped[dict] = mapped_column(JSON, default=dict)
    growing_files_json: Mapped[dict] = mapped_column(JSON, default=dict)
    logrotate_findings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    collected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(32), default="ssh")

    host: Mapped["Host"] = relationship(back_populates="directory_audits")


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    mount_point: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_gb: Mapped[float] = mapped_column(Float, nullable=False)
    requester: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    decisions: Mapped[list["Decision"]] = relationship(back_populates="request")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), nullable=False, index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    recommended_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    request: Mapped["Request"] = relationship(back_populates="decisions")
    overrides: Mapped[list["Override"]] = relationship(back_populates="decision")


class Override(Base):
    __tablename__ = "overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"), nullable=False, index=True)
    new_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    user: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    decision: Mapped["Decision"] = relationship(back_populates="overrides")
