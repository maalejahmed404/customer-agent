"""Validation humaine de chaque email (actions/ et agent/nodes/email_drafter.py)."""

import pytest

from actions import approval
from agent import llm as llm_module
from agent import mcp_client
from agent.graph import build_graph
from agent.state import EmailDraft, Plan
from tests.fakes import FakeLLM

EMAIL = {"to": ["helene.vasseur@clinique-saint-aubin.fr"], "subject": "Facture FAC-2291",
         "body": "Bonjour Hélène, nous corrigeons la facture."}


@pytest.fixture
def email_request(monkeypatch):
    """L'utilisateur demande un email ; le faux modèle le planifie et écrit `draft`."""
    async def call_tools(token, calls):
        return [{"results": []} for _ in calls]

    monkeypatch.setattr(mcp_client, "call_tools", call_tools)

    async def run(draft):
        fake = FakeLLM(plan=Plan(needs_data=False, draft_email=True), answer="Voici le brouillon.",
                       draft=draft)
        monkeypatch.setattr(llm_module, "get_llm", lambda: fake)
        return await build_graph().ainvoke({
            "question": "Écris à Hélène au sujet de la facture",
            "account_id": 1, "user_email": "camille@vendor.fr"})
    return run


async def test_l_agent_ne_fait_que_proposer_l_email(db, email_request):
    result = await email_request(EmailDraft(**EMAIL))

    action = await db.actions.find_one()
    assert str(action["_id"]) == result["action_id"]
    assert action["status"] == "pending" and action["payload"] == EMAIL
    assert await db.outbox.count_documents({}) == 0  # rien n'est envoyé sans un humain


async def test_un_destinataire_invalide_n_est_jamais_propose(db, email_request):
    result = await email_request(EmailDraft(**{**EMAIL, "to": ["helene, and evil@x.com"]}))

    assert result["action_id"] is None
    assert await db.actions.count_documents({}) == 0


async def test_l_approbation_envoie_l_email_une_seule_fois(db):
    action_id = await approval.propose(db, 1, "camille@vendor.fr", "send_email", EMAIL)

    approved = await approval.decide(db, 1, action_id, "manager@vendor.fr", approve=True)
    assert approved["status"] == "sent" and approved["decided_by"] == "manager@vendor.fr"
    assert await approval.decide(db, 1, action_id, "manager@vendor.fr", approve=True) is None
    assert await db.outbox.count_documents({}) == 1


async def test_un_refus_n_envoie_rien(db):
    action_id = await approval.propose(db, 1, "camille@vendor.fr", "send_email", EMAIL)

    rejected = await approval.decide(db, 1, action_id, "manager@vendor.fr", approve=False)
    assert rejected["status"] == "rejected"
    assert await db.outbox.count_documents({}) == 0


async def test_un_autre_compte_ne_peut_pas_approuver(db):
    action_id = await approval.propose(db, 1, "camille@vendor.fr", "send_email", EMAIL)

    assert await approval.decide(db, 2, action_id, "intruder@other.fr", approve=True) is None
    assert (await db.actions.find_one())["status"] == "pending"
    assert await db.outbox.count_documents({}) == 0
