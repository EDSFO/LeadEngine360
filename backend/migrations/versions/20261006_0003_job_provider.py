"""Persist the discovery provider chosen when a job is queued."""

from alembic import op
import sqlalchemy as sa

revision = "20261006_0003"
down_revision = "20261006_0002"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("job_runs")}
    if "provider_id" not in columns:
        op.add_column("job_runs", sa.Column("provider_id", sa.String(length=40), nullable=True))


def downgrade():
    op.drop_column("job_runs", "provider_id")
