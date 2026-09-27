"""S21 块 S：user + auth_token 表（协作与准入）

- user：username 唯一索引、password_hash（pbkdf2 格式串）、role 三级 admin/reviewer/viewer；
- auth_token：token_hash（SHA-256）唯一索引、expires_at；
- review.user_id：nullable（存量评审行回填 NULL，评审人身份以 reviewer 字符串为准）。

Revision ID: a1b2c3d4e5f6
Revises: d8a3f5c7e9b1
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "d8a3f5c7e9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_user_username"), "user", ["username"])
    op.create_table(
        "auth_token",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_auth_token_user_id"), "auth_token", ["user_id"])
    op.create_index(op.f("ix_auth_token_token_hash"), "auth_token", ["token_hash"])
    op.add_column("review", sa.Column("user_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("review", "user_id")
    op.drop_index(op.f("ix_auth_token_token_hash"), table_name="auth_token")
    op.drop_index(op.f("ix_auth_token_user_id"), table_name="auth_token")
    op.drop_table("auth_token")
    op.drop_index(op.f("ix_user_username"), table_name="user")
    op.drop_table("user")
