"""L'API HTTP : login, isolation des comptes par le token JWT, actions (api/)."""

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from actions import approval
from agent import llm as llm_module
from agent import mcp_client
from agent.graph import build_graph
from agent.state import Plan
from api import users
from api.dependencies import get_agent
from api.main import app
from shared import security
from tests.fakes import FakeLLM


@pytest.fixture
async def client(db):
    await users.create_user(db, "camille@vendor.fr", "good-password", 1)
    await db.accounts.insert_one({"_id": 1, "name": "Clinique Saint-Aubin"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


def use_agent(agent):
    """Remplace l'agent de l'API (c'est à ça que sert Depends(get_agent))."""
    app.dependency_overrides[get_agent] = lambda: agent


def auth(account_id, email="camille@vendor.fr"):
    return {"Authorization": f"Bearer {security.create_token(email, account_id)}"}


async def test_le_login_renvoie_un_token_pour_le_compte_de_l_utilisateur(client):
    response = await client.post("/login", json={"email": "Camille@vendor.fr",
                                                 "password": "good-password"})

    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == 1 and body["account_name"] == "Clinique Saint-Aubin"
    with_token = {"Authorization": f"Bearer {body['token']}"}
    assert (await client.get("/actions", headers=with_token)).status_code == 200


async def test_un_login_avec_un_mauvais_mot_de_passe_est_refuse(client):
    response = await client.post("/login", json={"email": "camille@vendor.fr", "password": "nope"})
    assert response.status_code == 401


async def test_le_chat_demande_un_token_valide(client):
    assert (await client.post("/chat", json={"question": "hello"})).status_code == 401
    bad = {"Authorization": "Bearer not.a.token"}
    assert (await client.post("/chat", json={"question": "hello"}, headers=bad)).status_code == 401


async def test_le_chat_utilise_le_compte_du_token(client):
    received = {}

    class FakeAgent:
        async def ainvoke(self, state, config):
            received.update(state, **config["configurable"])
            return {"answer": "ok", "sources": []}

    use_agent(FakeAgent())
    response = await client.post("/chat", headers=auth(1),
                                 json={"question": "Synthèse ?", "account_id": 2})

    assert response.status_code == 200
    assert received["account_id"] == 1  # l'account_id du corps de la requête est ignoré
    assert received["thread_id"].startswith("1:camille@vendor.fr:")


async def test_deux_utilisateurs_ne_partagent_jamais_une_conversation(client, monkeypatch):
    async def call_tools(token, calls):
        return [{"results": []} for _ in calls]

    fake = FakeLLM(plan=Plan(needs_data=False), answer="ok")
    monkeypatch.setattr(mcp_client, "call_tools", call_tools)
    monkeypatch.setattr(llm_module, "get_llm", lambda: fake)
    use_agent(build_graph(InMemorySaver()))

    same_id = {"conversation_id": "c1"}
    await client.post("/chat", headers=auth(1), json={"question": "Secret de Camille", **same_id})
    await client.post("/chat", headers=auth(1, "alex@vendor.fr"),
                      json={"question": "Bonjour", **same_id})

    alex_planner_prompt = fake.prompts[-2]
    assert "Secret de Camille" not in alex_planner_prompt
    assert "(no previous messages)" in alex_planner_prompt


async def test_chacun_ne_voit_et_n_approuve_que_ses_propres_actions(client, db):
    action_id = await approval.propose(db, 1, "camille@vendor.fr", "send_email",
                                       {"to": ["a@b.fr"], "subject": "Hi", "body": "Hello"})

    assert [a["id"] for a in (await client.get("/actions", headers=auth(1))).json()] == [action_id]
    assert (await client.get("/actions", headers=auth(2))).json() == []
    assert (await client.post(f"/actions/{action_id}/approve", headers=auth(2))).status_code == 404
    response = await client.post(f"/actions/{action_id}/approve", headers=auth(1))
    assert response.status_code == 200 and response.json()["status"] == "sent"
