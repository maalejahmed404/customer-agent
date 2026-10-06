"""L'agent LangGraph, avec un faux LLM et un faux serveur MCP (agent/)."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

from agent import llm as llm_module
from agent import mcp_client
from agent.graph import build_graph
from agent.nodes.retriever import fit_budget, fuse, plan_to_calls
from agent.state import EmailDraft, Plan
from shared import security
from shared.config import settings
from tests.fakes import FakeLLM

PASSAGES = [
    {"id": "c1", "interaction_id": "i1", "kind": "email", "date": "2025-03-10",
     "title": "Contestation de facture", "text": "La facture FAC-2291 est contestée.", "score": 1.0},
    {"id": "c2", "interaction_id": "i2", "kind": "call", "date": "2025-01-13",
     "title": "Appel de découverte", "text": "Occupation des salles à 62 %.", "score": 0.5},
]


@pytest.fixture
def fake_mcp(monkeypatch):
    """Enregistre les appels d'outils et renvoie PASSAGES pour chaque recherche."""
    received = []

    async def call_tools(token, calls):
        received.append((token, calls))
        return [{"results": PASSAGES} for _ in calls]

    monkeypatch.setattr(mcp_client, "call_tools", call_tools)
    return received


def use_llm(monkeypatch, fake_llm):
    monkeypatch.setattr(llm_module, "get_llm", lambda: fake_llm)
    return fake_llm


async def ask(question="Où en est la contestation de facture ?", graph=None, thread="t1"):
    graph = graph or build_graph()
    return await graph.ainvoke(
        {"question": question, "account_id": 1, "user_email": "camille@vendor.fr"},
        {"configurable": {"thread_id": thread}},
    )


# ------------------------------------------------------------ fonctions simples

def test_le_plan_donne_un_appel_d_outil_par_recherche():
    plan = Plan(needs_data=True, keyword_queries=["FAC-2291"], semantic_queries=["litige facture"],
                kind="email", date_from="le mois dernier", recent=True)

    assert plan.date_from is None  # une date mal écrite par le modèle est ignorée
    assert plan_to_calls(plan) == [
        ("keyword_search", {"query": "FAC-2291", "kind": "email"}),
        ("semantic_search", {"query": "litige facture", "kind": "email"}),
        ("list_interactions", {"kind": "email", "limit": 5}),
    ]


def test_la_fusion_prefere_les_passages_trouves_par_les_deux_recherches():
    a, b, c = ({"id": x, "text": ""} for x in "abc")
    keyword_results = [a, b]
    semantic_results = [c, b]

    assert [p["id"] for p in fuse([keyword_results, semantic_results])] == ["b", "a", "c"]


def test_les_sources_sont_coupees_au_budget():
    passages = [{"id": str(i), "text": "x" * 400} for i in range(10)]
    assert len(fit_budget(passages, 1000)) == 2


# ------------------------------------------------------------ le graphe complet

async def test_la_reponse_cite_des_sources_liees_a_leur_interaction(monkeypatch, fake_mcp):
    use_llm(monkeypatch, FakeLLM(plan=Plan(needs_data=True, keyword_queries=["facture"]),
                                 answer="La facture FAC-2291 est contestée [1]."))
    result = await ask()

    assert result["answer"] == "La facture FAC-2291 est contestée [1]."
    assert [(s["number"], s["interaction_id"]) for s in result["sources"]] == [(1, "i1")]
    token, _ = fake_mcp[0]
    assert security.decode_token(token)["account_id"] == 1  # le serveur MCP reçoit le compte de l'utilisateur


async def test_une_salutation_ne_lance_pas_de_recherche(monkeypatch, fake_mcp):
    use_llm(monkeypatch, FakeLLM(plan=Plan(needs_data=False), answer="Bonjour !"))
    result = await ask("Bonjour")

    assert result["answer"] == "Bonjour !"
    assert fake_mcp == []


async def test_si_le_planner_echoue_on_cherche_avec_la_question(monkeypatch, fake_mcp):
    use_llm(monkeypatch, FakeLLM(plan=RuntimeError("model unavailable"), answer="OK [1]"))
    await ask("contestation FAC-2291")

    [(_, calls)] = fake_mcp
    assert calls == [("keyword_search", {"query": "contestation FAC-2291", "kind": "any"}),
                     ("semantic_search", {"query": "contestation FAC-2291", "kind": "any"})]


async def test_les_sources_arrivent_au_modele_comme_donnees_non_fiables(monkeypatch, fake_mcp):
    fake = use_llm(monkeypatch, FakeLLM(plan=Plan(needs_data=True, keyword_queries=["facture"])))
    await ask()

    messages = fake.prompts[-1]
    system, human = messages[0], messages[-1]
    assert "FAC-2291" not in system[1]  # jamais dans le prompt système
    assert "<<<DATA" in human[1] and "FAC-2291" in human[1]


async def test_une_recherche_en_panne_ne_casse_pas_la_reponse(monkeypatch):
    async def call_tools(token, calls):
        return [RuntimeError("keyword search down"), {"results": PASSAGES[1:]}]

    monkeypatch.setattr(mcp_client, "call_tools", call_tools)
    use_llm(monkeypatch, FakeLLM(plan=Plan(needs_data=True, keyword_queries=["salles"],
                                           semantic_queries=["occupation"]),
                                 answer="62 % [1]"))
    result = await ask()

    assert result["sources"][0]["title"] == "Appel de découverte"


# ------------------------------------------------------------ mémoire de conversation

async def test_une_relance_voit_la_conversation_sauvee_dans_mongodb(mongo_db, monkeypatch, fake_mcp):
    fake = use_llm(monkeypatch, FakeLLM(plan=Plan(needs_data=True, keyword_queries=["facture"]),
                                        answer="La facture FAC-2291 est contestée [1]."))

    def new_graph():  # un nouveau graphe à chaque fois, comme une API redémarrée : la mémoire est dans MongoDB
        return build_graph(MongoDBSaver(MongoClient(settings.mongo_uri), db_name=settings.db_name))

    await ask("Où en est la facture FAC-2291 ?", graph=new_graph())
    await ask("Et qui l'a contestée ?", graph=new_graph())

    planner_prompts = [p for p in fake.prompts if isinstance(p, str)]
    assert "Où en est la facture FAC-2291 ?" in planner_prompts[1]
    assert "La facture FAC-2291 est contestée" in planner_prompts[1]
    responder_messages = fake.prompts[-1]
    assert [m.content for m in responder_messages[1:3]] == [
        "Où en est la facture FAC-2291 ?", "La facture FAC-2291 est contestée [1]."]
    assert await mongo_db.checkpoints.count_documents({}) > 0


async def test_chaque_question_repart_sans_l_email_precedent(db, monkeypatch, fake_mcp):
    graph = build_graph(InMemorySaver())
    use_llm(monkeypatch, FakeLLM(
        plan=Plan(needs_data=True, keyword_queries=["facture"], draft_email=True),
        draft=EmailDraft(to=["helene@clinique.fr"], subject="Facture", body="Bonjour")))
    first = await ask("Écris à Hélène au sujet de la facture", graph=graph)

    use_llm(monkeypatch, FakeLLM(plan=Plan(needs_data=True, keyword_queries=["salles"]),
                                 answer="62 % [2]"))
    second = await ask("Et le taux d'occupation ?", graph=graph)

    assert first["action_id"]
    assert second["action_id"] is None  # l'email de la première question n'est pas renvoyé
    assert [s["interaction_id"] for s in second["sources"]] == ["i2"]
