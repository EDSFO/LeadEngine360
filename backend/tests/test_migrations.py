import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.config import settings
from app.database import Base
from app import models


class MigrationTest(unittest.TestCase):
    def test_fresh_and_existing_pilot_database(self):
        root = Path(__file__).resolve().parents[1]
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "migrations"))
        with tempfile.TemporaryDirectory() as directory:
            for legacy in (False, True):
                path = Path(directory) / ("legacy.db" if legacy else "fresh.db")
                url = f"sqlite:///{path.as_posix()}"
                if legacy:
                    engine = create_engine(url)
                    new_tables = {"account_sources", "account_contacts", "user_invitations", "ai_calls", "workflow_runs", "workflow_steps"}
                    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name not in new_tables])
                    with engine.begin() as connection:
                        connection.execute(text("ALTER TABLE job_runs DROP COLUMN provider_id"))
                    with Session(engine) as db:
                        db.add(models.Tenant(id="existing-tenant", name="Empresa anterior"))
                        db.commit()
                    engine.dispose()
                with patch.object(settings, "database_url", url):
                    command.upgrade(config, "head")
                engine = create_engine(url)
                tables = set(inspect(engine).get_table_names())
                self.assertTrue({"tenants", "account_sources", "account_contacts", "user_invitations", "ai_calls", "workflow_runs", "workflow_steps", "alembic_version"}.issubset(tables))
                self.assertIn("provider_id", {column["name"] for column in inspect(engine).get_columns("job_runs")})
                with Session(engine) as db:
                    self.assertEqual(db.scalar(select(models.Tenant.name).where(models.Tenant.id == "existing-tenant")), "Empresa anterior" if legacy else None)
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
