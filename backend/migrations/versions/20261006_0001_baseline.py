"""Baseline current schema and add tables introduced after the pilot.

Existing deployments may already have the original tables created by
Base.metadata.create_all. The revision checks their columns and creates only
missing tables, preserving existing rows. It refuses a partial old table.
"""

from alembic import op
from sqlalchemy import inspect

from app.database import Base
from app import models  # noqa: F401 - registers ORM tables

revision = "20261006_0001"
down_revision = None
branch_labels = None
depends_on = None

BASELINE_TABLES = {
    "tenants", "job_runs", "seller_companies", "users", "offers", "user_invitations",
    "icp_profiles", "knowledge_documents", "offer_source_selections", "target_accounts",
    "account_activities", "account_briefs", "account_contacts", "account_scores",
    "account_sources", "ai_calls", "document_chunks", "intent_signals",
}


def upgrade() -> None:
    connection = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name not in BASELINE_TABLES:
            continue
        inspector = inspect(connection)
        if inspector.has_table(table.name):
            actual = {column["name"] for column in inspector.get_columns(table.name)}
            expected = set(table.columns.keys())
            if table.name == "job_runs":
                # Added in 0003 for databases created before provider selection.
                expected.discard("provider_id")
            missing = expected - actual
            if missing:
                raise RuntimeError(f"Tabela {table.name} incompleta; colunas ausentes: {', '.join(sorted(missing))}")
        else:
            table.create(connection, checkfirst=True)


def downgrade() -> None:
    raise NotImplementedError("A revisão inicial pode conter dados anteriores; restaure um backup para reverter")
