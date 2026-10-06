import asyncio
import io
import os
import unittest
from unittest.mock import Mock, patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["JWT_SECRET"] = "synthetic-test-only"

from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.discovery import DiscoveryConfigError, fetch_osm_accounts, overpass_query
from app.commercial_discovery import build_hunter_filters, fetch_apollo_accounts, fetch_hunter_accounts, fetch_hunter_contacts, fetch_hunter_company
from app.config import settings
from app.leads import calculate_score, create_activity, create_signal, get_account_brief, import_accounts, list_account_contacts, list_account_sources, list_accounts, start_discovery
from app.main import app, health, save_onboarding, update_icp
from app.main import list_ai_calls
from app.ai_audit import record_ai_calls
from app.database import get_db
from app.security import create_token
from app.models import IcpProfile, JobRun, Offer, OfferSourceSelection, Tenant, User, WorkflowRun
from app.schemas import ActivityIn, IcpUpdateIn, OnboardingIn, SignalIn
from app.tasks import discover_accounts, process_account, refresh_scores


PROFILE = {"ideal_customer_profile": {"segments": ["Tecnologia"], "company_size": ["51-200"], "regions": ["Brasil"]}}


class CoreFlowTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.db = self.sessions()
        tenant = Tenant(name="Empresa de teste")
        self.db.add(tenant)
        self.db.flush()
        self.user = User(tenant_id=tenant.id, email="teste@example.com", password_hash="unused")
        self.db.add(self.user)
        self.db.commit()
        company = save_onboarding(OnboardingIn(company_name=tenant.name, offers=[{"name": "Oferta de teste", "description": "Descrição da oferta para os testes"}]), self.db, self.user)
        self.offer_id = company["offers"][0]["id"]

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def approve(self):
        return update_icp(self.offer_id, IcpUpdateIn(profile=PROFILE, status="approved"), self.db, self.user)

    def test_icp_requires_usable_criteria(self):
        with self.assertRaises(HTTPException) as error:
            update_icp(self.offer_id, IcpUpdateIn(profile={}, status="approved"), self.db, self.user)
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(self.db.query(IcpProfile).count(), 0)

    def test_required_icp_criterion_blocks_mismatched_account(self):
        from app.models import TargetAccount

        profile = {"ideal_customer_profile": {**PROFILE["ideal_customer_profile"], "required": ["segments"]}}
        update_icp(self.offer_id, IcpUpdateIn(profile=profile, status="approved"), self.db, self.user)
        account = TargetAccount(tenant_id=self.user.tenant_id, offer_id=self.offer_id, name="Conta de teste", segment="Varejo", employee_band="51-200", region="Brasil")
        self.db.add(account)
        self.db.flush()
        icp = self.db.scalar(select(IcpProfile).where(IcpProfile.offer_id == self.offer_id))
        score = calculate_score(self.db, account, icp)
        self.assertEqual(score.fit, 0)
        self.assertEqual(score.classification, "Cold")
        self.assertEqual(score.explanation["missing_required_criteria"], ["segments"])

    def test_numeric_provider_headcount_matches_icp_band(self):
        from app.models import TargetAccount

        self.approve()
        account = TargetAccount(tenant_id=self.user.tenant_id, offer_id=self.offer_id, name="Empresa fictícia", segment="Tecnologia", employee_band="120", region="Brasil")
        self.db.add(account)
        self.db.flush()
        icp = self.db.scalar(select(IcpProfile).where(IcpProfile.offer_id == self.offer_id))
        self.assertEqual(calculate_score(self.db, account, icp).fit, 40)
        account.region = "Brazil"
        self.assertEqual(calculate_score(self.db, account, icp).fit, 40)
        account.employee_band = "500"
        self.assertLess(calculate_score(self.db, account, icp).fit, 40)

    def test_offer_limit_and_icp_invalidation(self):
        self.approve()
        first = self.db.get(Offer, self.offer_id)
        save_onboarding(OnboardingIn(company_name="Empresa de teste", offers=[{"id": first.id, "name": first.name, "description": "Descrição alterada para um novo mercado"}]), self.db, self.user)
        self.assertEqual(self.db.scalar(select(IcpProfile).where(IcpProfile.offer_id == first.id)).status, "draft")
        with self.assertRaises(HTTPException) as error:
            save_onboarding(OnboardingIn(company_name="Empresa de teste", offers=[{"name": f"Oferta {i}", "description": "Descrição da oferta para os testes"} for i in range(5)]), self.db, self.user)
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(self.db.query(Offer).count(), 1)

    def test_immediate_scores_and_duplicate_domain(self):
        self.approve()
        file = UploadFile(filename="synthetic.csv", file=io.BytesIO(b"empresa,dominio,segmento,porte,regiao\nConta A,example.com,Tecnologia,51-200,Brasil\nConta B,example.com,Tecnologia,51-200,Brasil\n"))
        imported = asyncio.run(import_accounts(self.offer_id, file, self.db, self.user))
        self.assertEqual((imported["created"], imported["updated"]), (1, 1))
        page = list_accounts(self.offer_id, None, None, 1, 0, self.db, self.user)
        self.assertEqual((page["total"], len(page["items"])), (1, 1))
        from app.models import TargetAccount

        account = self.db.scalar(select(TargetAccount).where(TargetAccount.offer_id == self.offer_id))
        signal = create_signal(self.offer_id, account.id, SignalIn(signal_type="expansion", title="Sinal de teste", description="Expansão identificada", confidence=1, strength=5), self.db, self.user)
        self.assertEqual(signal["score"]["total"], 80)
        activity = create_activity(self.offer_id, account.id, ActivityIn(activity_type="meeting"), self.db, self.user)
        self.assertEqual(activity["score"]["engagement"], 12)

    def test_discovery_requires_bounded_configuration_and_selected_source(self):
        self.approve()
        with self.assertRaises(HTTPException) as error:
            start_discovery(self.offer_id, self.db, self.user)
        self.assertEqual(error.exception.status_code, 409)
        self.db.add(OfferSourceSelection(tenant_id=self.user.tenant_id, offer_id=self.offer_id, provider_id="osm-overpass", enabled=True))
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            start_discovery(self.offer_id, self.db, self.user)
        self.assertEqual(error.exception.status_code, 422)

        configured = {**PROFILE, "discovery": {"osm_tag": {"key": "amenity", "value": "restaurant"}, "bbox": [-23.56, -46.65, -23.55, -46.64]}}
        update_icp(self.offer_id, IcpUpdateIn(profile=configured, status="approved"), self.db, self.user)
        with patch.object(discover_accounts, "delay") as enqueue:
            job = start_discovery(self.offer_id, self.db, self.user)
        self.assertEqual(job["status"], "queued")
        enqueue.assert_called_once()
        self.assertEqual(self.db.scalar(select(JobRun).where(JobRun.id == job["job_id"])).job_type, "account_discovery")
        self.assertIn('nwr["amenity"="restaurant"]', overpass_query(configured))
        with self.assertRaises(DiscoveryConfigError):
            overpass_query({**PROFILE, "discovery": {"osm_tag": {"key": "amenity", "value": "restaurant"}, "bbox": [-90, -180, 90, 180]}})

    def test_discovery_job_persists_and_scores_accounts(self):
        configured = {**PROFILE, "discovery": {"osm_tag": {"key": "amenity", "value": "restaurant"}, "bbox": [-23.56, -46.65, -23.55, -46.64]}}
        update_icp(self.offer_id, IcpUpdateIn(profile=configured, status="approved"), self.db, self.user)
        job = JobRun(tenant_id=self.user.tenant_id, entity_id=self.offer_id, job_type="account_discovery", status="queued")
        self.db.add(job)
        self.db.commit()
        candidate = {"name": "Restaurante de teste", "domain": None, "website": None, "segment": "Tecnologia", "region": "Brasil", "source": "osm-overpass", "external_id": "node/123", "source_url": "https://www.openstreetmap.org/node/123", "contact_email": "contato@example.com", "contact_phone": "+55 11 1234-5678"}
        with patch("app.tasks.SessionLocal", self.sessions), patch("app.discovery.fetch_osm_accounts", return_value=[candidate, candidate]), patch.object(process_account, "delay") as enqueue:
            result = discover_accounts.apply(args=[job.id, self.user.tenant_id, self.offer_id], throw=True).get()
        enqueue.assert_called_once()
        self.assertEqual((result["created"], result["updated"]), (1, 0))
        from app.models import AccountContact, AccountScore, AccountSource, TargetAccount, WorkflowRun, WorkflowStep, AccountBrief

        self.assertEqual(self.db.query(TargetAccount).count(), 1)
        self.assertEqual(self.db.query(AccountScore).count(), 1)
        self.assertEqual(self.db.query(AccountSource).count(), 1)
        self.assertEqual(self.db.query(AccountContact).count(), 1)
        run = self.db.scalar(select(WorkflowRun).where(WorkflowRun.discovery_job_id == job.id))
        self.assertEqual(run.status, "queued")
        with patch("app.tasks.SessionLocal", self.sessions):
            processed = process_account.apply(args=[run.id, self.user.tenant_id], throw=True).get()
        self.assertEqual(processed["status"], "completed")
        self.assertEqual(self.db.query(AccountBrief).count(), 1)
        self.assertEqual(self.db.query(WorkflowStep).filter(WorkflowStep.run_id == run.id).count(), 5)
        self.db.refresh(run)
        self.assertEqual(run.status, "completed")
        account = self.db.scalar(select(TargetAccount).where(TargetAccount.offer_id == self.offer_id))
        self.assertEqual(list_account_contacts(self.offer_id, account.id, self.db, self.user)[0]["kind"], "general")
        self.assertEqual(list_account_sources(self.offer_id, account.id, self.db, self.user)[0]["external_id"], "node/123")
        self.db.refresh(job)
        self.assertEqual(job.status, "completed")
        repeat = JobRun(tenant_id=self.user.tenant_id, entity_id=self.offer_id, job_type="account_discovery", status="queued")
        self.db.add(repeat)
        self.db.commit()
        with patch("app.tasks.SessionLocal", self.sessions), patch("app.discovery.fetch_osm_accounts", return_value=[candidate]), patch.object(process_account, "delay"):
            again = discover_accounts.apply(args=[repeat.id, self.user.tenant_id, self.offer_id], throw=True).get()
        self.assertEqual((again["created"], again["updated"]), (0, 1))
        self.assertEqual(self.db.query(TargetAccount).count(), 1)
        self.assertEqual(self.db.query(AccountContact).count(), 1)

    def test_osm_response_accepts_named_business_without_website(self):
        configured = {**PROFILE, "discovery": {"osm_tag": {"key": "amenity", "value": "restaurant"}, "bbox": [-23.56, -46.65, -23.55, -46.64]}}
        response = Mock()
        response.json.return_value = {"elements": [{"type": "node", "id": 123, "tags": {"name": "Empresa de teste", "amenity": "restaurant", "addr:city": "São Paulo", "contact:email": "Contato@Example.com", "contact:phone": "+55 11 1234-5678"}}]}
        with patch("app.discovery.httpx.post", return_value=response) as request:
            accounts = fetch_osm_accounts(configured)
        self.assertEqual(accounts[0]["external_id"], "node/123")
        self.assertIsNone(accounts[0]["domain"])
        self.assertEqual(accounts[0]["region"], "São Paulo")
        self.assertEqual(accounts[0]["contact_email"], "contato@example.com")
        self.assertEqual(accounts[0]["contact_phone"], "+55 11 1234-5678")
        request.assert_called_once()

    def test_apollo_and_hunter_adapters_use_bounded_official_api_calls(self):
        apollo = Mock()
        apollo.json.return_value = {"organizations": [{"id": "org-123", "name": "Empresa fictícia", "primary_domain": "example.com", "industry": "Tecnologia", "country": "Brasil", "estimated_num_employees": 120}]}
        with patch.object(settings, "apollo_api_key", "synthetic-test-key"), patch("app.commercial_discovery.httpx.post", return_value=apollo) as request:
            rows = fetch_apollo_accounts(PROFILE)
        self.assertEqual((rows[0]["provider_id"], rows[0]["external_id"]), ("apollo", "org-123"))
        self.assertEqual(request.call_args.args[0], "https://api.apollo.io/api/v1/mixed_companies/search")
        self.assertEqual(dict(request.call_args.kwargs["params"])["per_page"], 100)

        hunter = Mock()
        hunter.json.return_value = {"data": [{"domain": "example.org", "organization": "Outra empresa fictícia"}]}
        with patch.object(settings, "hunter_api_key", "synthetic-test-key"), patch("app.commercial_discovery.httpx.post", return_value=hunter) as request:
            rows = fetch_hunter_accounts(PROFILE)
        self.assertEqual(rows[0]["domain"], "example.org")
        self.assertIsNone(rows[0]["segment"])
        self.assertEqual(request.call_args.args[0], "https://api.hunter.io/v2/discover")
        self.assertEqual(request.call_args.kwargs["json"]["headquarters_location"]["include"], [{"country": "BR"}])

        hunter.json.return_value = {"data": {"emails": [{"value": "lead@example.org", "type": "personal", "first_name": "Pessoa", "last_name": "Fictícia", "position": "Diretora", "confidence": 92, "sources": [{"uri": "https://example.org/team"}] }]}}
        with patch.object(settings, "hunter_api_key", "synthetic-test-key"), patch("app.commercial_discovery.httpx.get", return_value=hunter) as request:
            contacts = fetch_hunter_contacts("example.org")
        self.assertEqual((contacts[0]["kind"], contacts[0]["confidence"]), ("person", 0.92))
        self.assertEqual(request.call_args.args[0], "https://api.hunter.io/v2/domain-search")

        hunter.status_code = 200
        hunter.json.return_value = {"data": {"category": {"industry": "Tecnologia"}, "metrics": {"employees": "51-200"}, "geo": {"country": "Brasil"}}}
        with patch.object(settings, "hunter_api_key", "synthetic-test-key"), patch("app.commercial_discovery.httpx.get", return_value=hunter) as request:
            company = fetch_hunter_company("example.org")
        self.assertEqual(company["employee_band"], "51-200")
        self.assertEqual(request.call_args.args[0], "https://api.hunter.io/v2/companies/find")

    def test_hunter_discovery_worker_uses_selected_provider(self):
        self.approve()
        self.db.add(OfferSourceSelection(tenant_id=self.user.tenant_id, offer_id=self.offer_id, provider_id="hunter", enabled=True))
        self.db.commit()
        with patch.object(settings, "hunter_api_key", "synthetic-test-key"), patch.object(discover_accounts, "delay"):
            queued = start_discovery(self.offer_id, self.db, self.user, provider_id="hunter")
        job = self.db.get(JobRun, queued["job_id"])
        self.assertEqual(job.provider_id, "hunter")
        candidate = {"name": "Empresa fictícia", "domain": "example.org", "website": "https://example.org", "segment": None, "region": None, "source": "hunter", "external_id": "example.org", "source_url": "https://example.org", "contact_email": None, "contact_phone": None}
        with patch("app.tasks.SessionLocal", self.sessions), patch("app.commercial_discovery.fetch_hunter_accounts", return_value=[candidate]) as fetch, patch.object(process_account, "delay"):
            result = discover_accounts.apply(args=[job.id, self.user.tenant_id, self.offer_id], throw=True).get()
        self.assertEqual((result["status"], result["created"]), ("completed", 1))
        fetch.assert_called_once()
        from app.models import AccountSource
        self.assertEqual(self.db.scalar(select(AccountSource.provider_id)), "hunter")
        run = self.db.scalar(select(WorkflowRun).where(WorkflowRun.discovery_job_id == job.id))
        with patch.object(settings, "hunter_api_key", "synthetic-test-key"), patch("app.tasks.SessionLocal", self.sessions), patch("app.commercial_discovery.fetch_hunter_company", return_value={"segment": "Tecnologia", "employee_band": "51-200", "region": "Brasil"}) as enrich, patch("app.commercial_discovery.fetch_hunter_contacts", return_value=[{"email": "person@example.org", "name": "Pessoa Fictícia", "title": "Diretora", "phone": None, "kind": "person", "confidence": 0.9, "source_url": "https://example.org/team"}]) as contacts:
            processed = process_account.apply(args=[run.id, self.user.tenant_id], throw=True).get()
        self.assertEqual(processed["status"], "completed")
        self.assertEqual(processed["score"], 40)
        enrich.assert_called_once_with("example.org")
        contacts.assert_called_once_with("example.org")

    def test_hunter_rejects_unsupported_region_before_queueing(self):
        profile = {"ideal_customer_profile": {"regions": ["São Paulo"]}}
        with self.assertRaises(DiscoveryConfigError):
            build_hunter_filters(profile)
        update_icp(self.offer_id, IcpUpdateIn(profile=profile, status="approved"), self.db, self.user)
        self.db.add(OfferSourceSelection(tenant_id=self.user.tenant_id, offer_id=self.offer_id, provider_id="hunter", enabled=True))
        self.db.commit()
        with patch.object(settings, "hunter_api_key", "synthetic-test-key"), self.assertRaises(HTTPException) as error:
            start_discovery(self.offer_id, self.db, self.user, provider_id="hunter")
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(self.db.query(JobRun).count(), 0)

    def test_apollo_discovery_keeps_company_size_for_scoring(self):
        from app.models import AccountScore, TargetAccount

        self.approve()
        self.db.add(OfferSourceSelection(tenant_id=self.user.tenant_id, offer_id=self.offer_id, provider_id="apollo", enabled=True))
        self.db.commit()
        with patch.object(settings, "apollo_api_key", "synthetic-test-key"), patch.object(discover_accounts, "delay"):
            queued = start_discovery(self.offer_id, self.db, self.user, provider_id="apollo")
        candidate = {"name": "Empresa fictícia", "domain": "example.com", "website": "https://example.com", "segment": "Tecnologia", "employee_band": "120", "region": "Brazil", "source": "apollo", "external_id": "org-123", "source_url": "https://example.com", "contact_email": None, "contact_phone": None}
        with patch("app.tasks.SessionLocal", self.sessions), patch("app.commercial_discovery.fetch_apollo_accounts", return_value=[candidate]), patch.object(process_account, "delay"):
            result = discover_accounts.apply(args=[queued["job_id"], self.user.tenant_id, self.offer_id], throw=True).get()
        self.assertEqual(result["created"], 1)
        account = self.db.scalar(select(TargetAccount).where(TargetAccount.offer_id == self.offer_id))
        self.assertEqual(account.employee_band, "120")
        self.assertEqual(self.db.scalar(select(AccountScore).where(AccountScore.account_id == account.id)).fit, 40)

    def test_discovery_http_contract(self):
        configured = {**PROFILE, "discovery": {"osm_tag": {"key": "amenity", "value": "restaurant"}, "bbox": [-23.56, -46.65, -23.55, -46.64]}}
        update_icp(self.offer_id, IcpUpdateIn(profile=configured, status="approved"), self.db, self.user)
        self.db.add(OfferSourceSelection(tenant_id=self.user.tenant_id, offer_id=self.offer_id, provider_id="osm-overpass", enabled=True))
        self.db.commit()
        def test_db():
            session = self.sessions()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = test_db
        try:
            with patch.object(discover_accounts, "delay"):
                response = TestClient(app).post(f"/api/v1/offers/{self.offer_id}/discovery", headers={"Authorization": f"Bearer {create_token(self.user)}"})
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["job_id"]
            latest = TestClient(app).get(f"/api/v1/offers/{self.offer_id}/discovery", headers={"Authorization": f"Bearer {create_token(self.user)}"})
            self.assertEqual(latest.status_code, 200)
            self.assertEqual(latest.json()["job_id"], job_id)
        finally:
            app.dependency_overrides.clear()

    def test_workflow_status_and_retry_are_tenant_scoped(self):
        from app.models import TargetAccount

        self.approve()
        account = TargetAccount(tenant_id=self.user.tenant_id, offer_id=self.offer_id, name="Empresa fictícia")
        self.db.add(account)
        self.db.flush()
        run = WorkflowRun(tenant_id=self.user.tenant_id, offer_id=self.offer_id, account_id=account.id, status="failed", error="Falha fictícia")
        self.db.add(run)
        self.db.commit()

        def test_db():
            session = self.sessions()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = test_db
        try:
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {create_token(self.user)}"}
            base = f"/api/v1/offers/{self.offer_id}/workflows"
            listing = client.get(base, headers=headers)
            self.assertEqual((listing.status_code, listing.json()["total"]), (200, 1))
            self.assertEqual(client.get(f"{base}/{run.id}", headers=headers).json()["status"], "failed")
            with patch.object(process_account, "delay") as enqueue:
                retried = client.post(f"{base}/{run.id}/retry", headers=headers)
            self.assertEqual((retried.status_code, retried.json()["status"]), (202, "queued"))
            enqueue.assert_called_once_with(run.id, self.user.tenant_id)
            self.assertEqual(client.post(f"{base}/{run.id}/retry", headers=headers).status_code, 409)
            other = Tenant(name="Outra empresa fictícia")
            self.db.add(other)
            self.db.flush()
            outsider = User(tenant_id=other.id, email="other-workflow@example.com", password_hash="unused")
            self.db.add(outsider)
            self.db.commit()
            outsider_headers = {"Authorization": f"Bearer {create_token(outsider)}"}
            self.assertEqual(client.get(base, headers=outsider_headers).status_code, 404)
            self.assertEqual(client.get(f"{base}/{run.id}", headers=outsider_headers).status_code, 404)
        finally:
            app.dependency_overrides.clear()

    def test_saved_brief_can_be_reopened(self):
        from app.models import AccountBrief, TargetAccount

        account = TargetAccount(tenant_id=self.user.tenant_id, offer_id=self.offer_id, name="Conta de teste")
        self.db.add(account)
        self.db.flush()
        self.db.add(AccountBrief(tenant_id=self.user.tenant_id, offer_id=self.offer_id, account_id=account.id, brief_json={"summary": "Exemplo"}, generated_with="test"))
        self.db.commit()
        result = get_account_brief(self.offer_id, account.id, self.db, self.user)
        self.assertEqual(result["brief"]["summary"], "Exemplo")

    def test_periodic_score_refresh(self):
        from app.models import AccountScore, TargetAccount

        self.approve()
        account = TargetAccount(tenant_id=self.user.tenant_id, offer_id=self.offer_id, name="Conta de teste", segment="Tecnologia", employee_band="51-200", region="Brasil")
        self.db.add(account)
        self.db.commit()
        with patch("app.tasks.SessionLocal", self.sessions):
            result = refresh_scores.apply(throw=True).get()
        self.assertEqual(result["refreshed"], 1)
        score = self.db.scalar(select(AccountScore).where(AccountScore.account_id == account.id))
        self.assertEqual(score.fit, 40)

    def test_invitation_and_role_permissions(self):
        from app.models import TargetAccount

        self.approve()
        account = TargetAccount(tenant_id=self.user.tenant_id, offer_id=self.offer_id, name="Conta de teste")
        self.db.add(account)
        self.db.commit()

        def test_db():
            session = self.sessions()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = test_db
        try:
            client = TestClient(app)
            admin_headers = {"Authorization": f"Bearer {create_token(self.user)}"}
            invitation = client.post("/api/v1/users/invitations", json={"email": "sdr@example.com", "role": "sdr"}, headers=admin_headers)
            self.assertEqual(invitation.status_code, 201)
            accepted = client.post("/api/v1/auth/accept-invitation", json={"token": invitation.json()["token"], "password": "synthetic-password-123"})
            self.assertEqual(accepted.status_code, 201)
            self.assertEqual(client.post("/api/v1/auth/accept-invitation", json={"token": invitation.json()["token"], "password": "synthetic-password-123"}).status_code, 410)
            sdr_headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
            self.assertEqual(client.put(f"/api/v1/offers/{self.offer_id}/icp", json={"profile": PROFILE, "status": "approved"}, headers=sdr_headers).status_code, 403)
            self.assertEqual(client.get("/api/v1/users", headers=sdr_headers).status_code, 403)
            self.assertEqual(client.post(f"/api/v1/offers/{self.offer_id}/accounts/{account.id}/activities", json={"activity_type": "contacted"}, headers=sdr_headers).status_code, 201)
            self.assertEqual(len(client.get("/api/v1/users", headers=admin_headers).json()), 2)
            self.assertEqual(client.patch(f"/api/v1/users/{self.user.id}/role", json={"role": "manager"}, headers=admin_headers).status_code, 409)
        finally:
            app.dependency_overrides.clear()

    def test_ai_call_audit_is_scoped_to_offer_and_tenant(self):
        record_ai_calls(self.db, self.user.tenant_id, self.offer_id, "generate_profile", [
            {"model": "primary", "status": "failed", "latency_ms": 120, "error_type": "HTTPStatusError"},
            {"model": "secondary", "status": "completed", "latency_ms": 220, "prompt_tokens": 50, "completion_tokens": 12, "cost_usd": 0.001},
        ])
        self.db.commit()
        calls = list_ai_calls(self.offer_id, 50, self.db, self.user)
        self.assertEqual({item["model"] for item in calls}, {"primary", "secondary"})
        self.assertEqual(next(item for item in calls if item["model"] == "secondary")["prompt_tokens"], 50)
        other = User(tenant_id="different-tenant", email="other@example.com", password_hash="unused", role="admin")
        with self.assertRaises(HTTPException) as error:
            list_ai_calls(self.offer_id, 50, self.db, other)
        self.assertEqual(error.exception.status_code, 404)

    def test_health_checks_database_and_queue(self):
        queue = Mock()
        with patch("app.main.Redis.from_url", return_value=queue):
            result = health(self.db)
        self.assertEqual((result["database"], result["queue"]), ("ok", "ok"))
        queue.ping.assert_called_once()
        queue.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
