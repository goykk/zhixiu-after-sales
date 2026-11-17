"""repair decision and outcome tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14

新增配件、兼容关系、审批、工单与维修结果 5 张表；不删除/修改既有表与列。
与 ``core.db.base.create_all()`` 建出相同表结构。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("part_no", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("stock_status", sa.String(length=32), nullable=False),
        sa.Column("hardware_range", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "part_no", name="uq_parts_device_partno"),
    )
    op.create_index(op.f("ix_parts_device_id"), "parts", ["device_id"], unique=False)

    op.create_table(
        "part_compatibilities",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_part_no", sa.String(length=64), nullable=False),
        sa.Column("target_part_no", sa.String(length=64), nullable=False),
        sa.Column("compatibility_type", sa.String(length=32), nullable=False),
        sa.Column("hardware_range", sa.String(length=128), nullable=False),
        sa.Column("evidence_source", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_part_no", "target_part_no", name="uq_part_compat_pair"
        ),
    )

    op.create_table(
        "work_orders",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assignee", sa.String(length=128), nullable=True),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_work_orders_case_id"), "work_orders", ["case_id"], unique=False)
    op.create_index(
        op.f("ix_work_orders_idempotency_key"),
        "work_orders",
        ["idempotency_key"],
        unique=True,
    )

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("approver_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approvals_case_id"), "approvals", ["case_id"], unique=False)

    op.create_table(
        "repair_outcomes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("work_order_id", sa.String(length=64), nullable=False),
        sa.Column("technician_id", sa.String(length=64), nullable=False),
        sa.Column("actual_cause_code", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("parts_replaced", sa.JSON(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_order_id"),
    )


def downgrade() -> None:
    op.drop_table("repair_outcomes")
    op.drop_index(op.f("ix_approvals_case_id"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(op.f("ix_work_orders_idempotency_key"), table_name="work_orders")
    op.drop_index(op.f("ix_work_orders_case_id"), table_name="work_orders")
    op.drop_table("work_orders")
    op.drop_table("part_compatibilities")
    op.drop_index(op.f("ix_parts_device_id"), table_name="parts")
    op.drop_table("parts")