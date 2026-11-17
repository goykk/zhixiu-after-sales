"""eval run records table

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14

新增评测运行记录表；不删除/修改既有表与列。
与 ``core.db.base.create_all()`` 建出相同表结构（``run_id`` 唯一索引）。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "eval_run_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("split", sa.String(length=32), nullable=False),
        sa.Column("strategies", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("gate", sa.JSON(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("report_paths", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_eval_run_records_run_id"),
        "eval_run_records",
        ["run_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_eval_run_records_run_id"), table_name="eval_run_records")
    op.drop_table("eval_run_records")