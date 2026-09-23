"""raw_event page_id and composite unique

Revision ID: 24574ffda624
Revises: cac56092f499
Create Date: 2026-09-23 17:42:57.618924

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '24574ffda624'
down_revision: Union[str, Sequence[str], None] = 'cac56092f499'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE TABLE raw_event_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(36) NOT NULL,
            page_id VARCHAR(40) NOT NULL DEFAULT '',
            seq INTEGER NOT NULL,
            ts BIGINT NOT NULL,
            kind VARCHAR(20) NOT NULL,
            payload JSON,
            created_at DATETIME,
            CONSTRAINT uq_raw_event_session_page_seq UNIQUE (session_id, page_id, seq)
        )
    """)
    op.execute("""
        INSERT INTO raw_event_new (id, session_id, page_id, seq, ts, kind, payload, created_at)
        SELECT id, session_id, '', seq, ts, kind, payload, created_at FROM raw_event
    """)
    op.execute("DROP TABLE raw_event")
    op.execute("ALTER TABLE raw_event_new RENAME TO raw_event")
    op.execute("CREATE INDEX ix_raw_event_session_id ON raw_event (session_id)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        CREATE TABLE raw_event_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(36) NOT NULL,
            seq INTEGER NOT NULL,
            ts BIGINT NOT NULL,
            kind VARCHAR(20) NOT NULL,
            payload JSON,
            created_at DATETIME,
            CONSTRAINT uq_raw_event_session_seq UNIQUE (session_id, seq)
        )
    """)
    op.execute("""
        INSERT INTO raw_event_old (id, session_id, seq, ts, kind, payload, created_at)
        SELECT id, session_id, seq, ts, kind, payload, created_at FROM raw_event
    """)
    op.execute("DROP TABLE raw_event")
    op.execute("ALTER TABLE raw_event_old RENAME TO raw_event")
    op.execute("CREATE INDEX ix_raw_event_session_id ON raw_event (session_id)")
