"""三轮评审：discovered_feature 去重查询索引。

该表是全局累加资产（不随 re-process 清），而 ingestion/discovery.py 对每个候选
都做一次 `api_template == value` / `anchor_label == value` 的存在性查询——无索引
即每候选一次全表扫。change/expected.py 的对齐查询同列。
"""
revision = "a3f1c8d2e6b4"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.create_index("ix_discovered_feature_api_template",
                    "discovered_feature", ["api_template"])
    op.create_index("ix_discovered_feature_anchor_label",
                    "discovered_feature", ["anchor_label"])


def downgrade() -> None:
    op.drop_index("ix_discovered_feature_anchor_label", "discovered_feature")
    op.drop_index("ix_discovered_feature_api_template", "discovered_feature")
