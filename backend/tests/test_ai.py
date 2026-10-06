import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["OPENROUTER_API_KEY"] = ""

from app.ai import generate_account_brief, generate_profile
from app.config import settings


class AiFallbackTest(unittest.TestCase):
    def test_falls_back_to_second_configured_model(self):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        failure = httpx.Response(503, request=request)
        success = httpx.Response(200, json={"choices": [{"message": {"content": '{"ideal_customer_profile":{"segments":["Tecnologia"]}}'}}], "usage": {"prompt_tokens": 120, "completion_tokens": 30, "cost": 0.001}}, request=request)
        client = MagicMock()
        client.post = AsyncMock(side_effect=[failure, success])
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        trace = []
        with patch.object(settings, "openrouter_api_key", "synthetic-test-key"), patch.object(settings, "openrouter_model", "model-primary"), patch.object(settings, "openrouter_fallback_models", "model-secondary"), patch("app.ai.httpx.AsyncClient", return_value=context):
            profile, model = asyncio.run(generate_profile({}, {"description": "Oferta de teste para empresas"}, [], trace))
        self.assertEqual(model, "model-secondary")
        self.assertEqual(profile["ideal_customer_profile"]["segments"], ["Tecnologia"])
        self.assertEqual([call.kwargs["json"]["model"] for call in client.post.call_args_list], ["model-primary", "model-secondary"])
        self.assertEqual([item["status"] for item in trace], ["failed", "completed"])
        self.assertEqual(trace[1]["prompt_tokens"], 120)

    def test_brief_heuristic_does_not_assert_unconfirmed_fit(self):
        with patch.object(settings, "openrouter_api_key", None):
            brief, model = asyncio.run(generate_account_brief({"name": "Oferta"}, {"name": "Conta"}, [], {"fit": 0, "total": 0, "explanation": {"matched_fit_criteria": []}}, {}))
        self.assertEqual(model, "heuristic")
        self.assertIn("Não há critérios de Fit confirmados", brief["offer_fit_hypothesis"])


if __name__ == "__main__":
    unittest.main()
