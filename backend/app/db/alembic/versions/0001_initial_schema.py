"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-22

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hosts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hostname", sa.String(length=255), nullable=False, unique=True),
        sa.Column("dt_entity_id", sa.String(length=128), nullable=True),
        sa.Column("environment", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hosts_hostname", "hosts", ["hostname"])

    op.create_table(
        "disk_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("host_id", sa.Integer(), sa.ForeignKey("hosts.id"), nullable=False),
        sa.Column("mount_point", sa.String(length=255), nullable=False),
        sa.Column("capacity_bytes", sa.BigInteger(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("used_pct", sa.Float(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_disk_metrics_host_id", "disk_metrics", ["host_id"])
    op.create_index("ix_disk_metrics_collected_at", "disk_metrics", ["collected_at"])

    op.create_table(
        "directory_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("host_id", sa.Integer(), sa.ForeignKey("hosts.id"), nullable=False),
        sa.Column("mount_point", sa.String(length=255), nullable=False),
        sa.Column("top_dirs_json", sa.JSON(), nullable=False),
        sa.Column("growing_files_json", sa.JSON(), nullable=False),
        sa.Column("logrotate_findings_json", sa.JSON(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_directory_audits_host_id", "directory_audits", ["host_id"])
    op.create_index("ix_directory_audits_collected_at", "directory_audits", ["collected_at"])

    op.create_table(
        "requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.String(length=64), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("mount_point", sa.String(length=255), nullable=False),
        sa.Column("requested_gb", sa.Float(), nullable=False),
        sa.Column("requester", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_requests_ticket_id", "requests", ["ticket_id"])
    op.create_index("ix_requests_created_at", "requests", ["created_at"])

    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("requests.id"), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("recommended_gb", sa.Float(), nullable=True),
        sa.Column("reasoning_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decisions_request_id", "decisions", ["request_id"])
    op.create_index("ix_decisions_created_at", "decisions", ["created_at"])

    op.create_table(
        "overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("new_decision", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=False),
        sa.Column("user", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_overrides_decision_id", "overrides", ["decision_id"])
    op.create_index("ix_overrides_created_at", "overrides", ["created_at"])


def downgrade() -> None:
    op.drop_table("overrides")
    op.drop_table("decisions")
    op.drop_table("requests")
    op.drop_table("directory_audits")
    op.drop_table("disk_metrics")
    op.drop_table("hosts")
