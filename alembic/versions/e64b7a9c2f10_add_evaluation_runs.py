"""add evaluation runs and cases

Revision ID: e64b7a9c2f10
Revises: c2e8d4a61f03
Create Date: 2026-08-30 02:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e64b7a9c2f10"
down_revision: str | Sequence[str] | None = "c2e8d4a61f03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("dialect", sa.String(length=32), nullable=False),
        sa.Column("system_time", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("total_cases", sa.Integer(), nullable=False),
        sa.Column("processed_cases", sa.Integer(), nullable=False),
        sa.Column("failed_cases", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.String(length=255), nullable=True),
        sa.Column("package_version", sa.String(length=64), nullable=True),
        sa.Column("package_sha256", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluation_runs_user_created",
        "evaluation_runs",
        ["user_id", "created_at"],
    )
    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("case_number", sa.Integer(), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("requirement", sa.Text(), nullable=False),
        sa.Column("reference_sql", sa.Text(), nullable=False),
        sa.Column("legacy_sql", sa.Text(), nullable=True),
        sa.Column("ontology_sql", sa.Text(), nullable=True),
        sa.Column("generation_status", sa.String(length=24), nullable=False),
        sa.Column("ontology_status", sa.String(length=32), nullable=True),
        sa.Column("ontology_evidence", sa.JSON(), nullable=True),
        sa.Column("temporal_decisions", sa.JSON(), nullable=True),
        sa.Column("reference_structure", sa.JSON(), nullable=True),
        sa.Column("legacy_structure", sa.JSON(), nullable=True),
        sa.Column("ontology_structure", sa.JSON(), nullable=True),
        sa.Column("legacy_comparison", sa.JSON(), nullable=True),
        sa.Column("ontology_comparison", sa.JSON(), nullable=True),
        sa.Column("diagnosis_codes", sa.JSON(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["evaluation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "case_number", name="uq_evaluation_case_number"),
    )
    op.create_index(
        "ix_evaluation_cases_run_number",
        "evaluation_cases",
        ["run_id", "case_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_cases_run_number", table_name="evaluation_cases")
    op.drop_table("evaluation_cases")
    op.drop_index("ix_evaluation_runs_user_created", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
