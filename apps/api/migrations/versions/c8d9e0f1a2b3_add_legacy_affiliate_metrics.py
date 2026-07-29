"""add legacy affiliate reconciliation fields

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "bbu_affiliate" not in sa.inspect(bind).get_table_names():
        return
    op.execute(
        """
        ALTER TABLE bbu_affiliate
          ADD COLUMN IF NOT EXISTS legacy_external_id VARCHAR(64) NOT NULL DEFAULT '',
          ADD COLUMN IF NOT EXISTS legacy_status VARCHAR(24) NOT NULL DEFAULT '',
          ADD COLUMN IF NOT EXISTS legacy_payout_email VARCHAR(320) NOT NULL DEFAULT '',
          ADD COLUMN IF NOT EXISTS legacy_visitors_count INTEGER NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS legacy_leads_count INTEGER NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS legacy_conversions_count INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_bbu_affiliate_legacy_external_id
        ON bbu_affiliate (legacy_external_id)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bbu_affiliate_ref_alias (
          id SERIAL PRIMARY KEY,
          org_id INTEGER NOT NULL,
          affiliate_id INTEGER NOT NULL,
          ref_code VARCHAR(64) NOT NULL UNIQUE,
          source VARCHAR(24) NOT NULL DEFAULT '',
          legacy_external_id VARCHAR(64) NOT NULL DEFAULT '',
          created_at VARCHAR(40) NOT NULL DEFAULT '',
          extra JSON
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_bbu_affiliate_ref_alias_org_id
        ON bbu_affiliate_ref_alias (org_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_bbu_affiliate_ref_alias_affiliate_id
        ON bbu_affiliate_ref_alias (affiliate_id)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_bbu_affiliate_ref_alias_ref_code
        ON bbu_affiliate_ref_alias (ref_code)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_bbu_affiliate_ref_alias_legacy_external_id
        ON bbu_affiliate_ref_alias (legacy_external_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bbu_affiliate_ref_alias")
    op.execute("DROP INDEX IF EXISTS ix_bbu_affiliate_legacy_external_id")
    op.execute(
        """
        ALTER TABLE bbu_affiliate
          DROP COLUMN IF EXISTS legacy_conversions_count,
          DROP COLUMN IF EXISTS legacy_leads_count,
          DROP COLUMN IF EXISTS legacy_visitors_count,
          DROP COLUMN IF EXISTS legacy_payout_email,
          DROP COLUMN IF EXISTS legacy_status,
          DROP COLUMN IF EXISTS legacy_external_id
        """
    )
