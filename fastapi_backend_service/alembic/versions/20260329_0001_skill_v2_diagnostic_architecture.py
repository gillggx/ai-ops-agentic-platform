"""skill v2.0 — diagnostic-first architecture

Revision ID: 20260329_0001
Revises: 20260312_0001
Create Date: 2026-03-29

Changes:
  - skill_definitions: add output_schema column
  - auto_patrols: new table for event/schedule-driven skill execution + alarm decisions
"""
from alembic import op
import sqlalchemy as sa

revision = "20260329_0001"
down_revision = "20260312_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── skill_definitions: add output_schema ─────────────────────────────────
    op.add_column(
        "skill_definitions",
        sa.Column("output_schema", sa.Text(), nullable=True, server_default="[]"),
    )

    # ── auto_patrols: new table ───────────────────────────────────────────────
    op.create_table(
        "auto_patrols",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        # Skill to execute
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skill_definitions.id", ondelete="CASCADE"), nullable=False),
        # "event" | "schedule"
        sa.Column("trigger_mode", sa.String(20), nullable=False, server_default="schedule"),
        # For trigger_mode="event": which event type triggers this patrol
        sa.Column("event_type_id", sa.Integer(), sa.ForeignKey("event_types.id", ondelete="SET NULL"), nullable=True),
        # For trigger_mode="schedule": cron expression
        sa.Column("cron_expr", sa.String(100), nullable=True),
        # JSON: {type: "all_equipment"|"equipment_list"|"event_driven", equipment_ids: [...]}
        sa.Column("target_scope", sa.Text(), nullable=False, server_default='{"type":"event_driven"}'),
        # Alarm config — applied when skill findings.condition_met == True
        sa.Column("alarm_severity", sa.String(20), nullable=True),
        sa.Column("alarm_title", sa.String(300), nullable=True),
        # JSON: {channels: ["email","slack"], users: [...]}
        sa.Column("notify_config", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auto_patrols_skill_id", "auto_patrols", ["skill_id"])
    op.create_index("ix_auto_patrols_event_type_id", "auto_patrols", ["event_type_id"])
    op.create_index("ix_auto_patrols_is_active", "auto_patrols", ["is_active"])


def downgrade() -> None:
    op.drop_table("auto_patrols")
    op.drop_column("skill_definitions", "output_schema")
