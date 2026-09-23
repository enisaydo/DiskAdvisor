"""purge disk_metrics rows collected before the mount-point resolution fix

Every disk on a host used to collapse into one "/" bucket because the
collector trusted the Metrics API response's own (missing/unreliable on
this tenant) mountPoint dimension text instead of resolving the real path
via the Entities API. Rows collected before that fix mix multiple
filesystems' usage together under the same mount_point label (observed as
e.g. an impossible "used 200%" on a host that really has "/" at 53% and
"/var/log/audit" at 100% as two separate filesystems).

These rows would otherwise sit inside the 7/14-day growth-trend lookback
windows and keep corrupting fleet-wide top-growth/high-usage figures and
per-request scoring for one to two weeks after the fix is deployed.
disk_metrics is a derived, continuously-repopulated cache (not an
audit/compliance record), so a full purge is safe: the next
diskadvisor-collector run repopulates it correctly.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM disk_metrics")


def downgrade() -> None:
    # Data purge -- the deleted rows cannot be reconstructed.
    pass
