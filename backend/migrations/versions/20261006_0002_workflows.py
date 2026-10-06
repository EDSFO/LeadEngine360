"""Add account workflow runs and steps."""

from alembic import op

from app.database import Base
from app import models  # noqa: F401

revision = "20261006_0002"
down_revision = "20261006_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    Base.metadata.tables["workflow_runs"].create(connection, checkfirst=True)
    Base.metadata.tables["workflow_steps"].create(connection, checkfirst=True)


def downgrade() -> None:
    op.drop_table("workflow_steps")
    op.drop_table("workflow_runs")
