"""Le vrai serveur MCP, appelé en HTTP comme le fait l'agent (mcp_server/server.py)."""

import asyncio
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agent import mcp_client
from shared import search, security
from shared.config import settings


async def open_session(url, headers, action):
    async with httpx.AsyncClient(headers=headers) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await action(session)


async def test_les_outils_n_ont_pas_d_argument_account_id(mcp_url):
    headers = {"Authorization": f"Bearer {security.create_token('camille@vendor.fr', 1)}"}
    tools = (await open_session(mcp_url, headers, lambda s: s.list_tools())).tools

    assert {tool.name for tool in tools} == {"keyword_search", "semantic_search",
                                             "list_interactions", "get_interaction"}
    for tool in tools:
        assert "account_id" not in tool.inputSchema["properties"]
        assert "ctx" not in tool.inputSchema["properties"]


async def test_un_appel_sans_token_valide_est_refuse(mcp_url, sample_data):
    async def search_facture(session):
        return await session.call_tool("keyword_search", {"query": "facture"})

    assert (await open_session(mcp_url, {}, search_facture)).isError
    forged = {"Authorization": "Bearer forged.token.value"}
    assert (await open_session(mcp_url, forged, search_facture)).isError


async def test_le_compte_vient_du_token(mcp_url, sample_data, monkeypatch):
    monkeypatch.setattr(settings, "mcp_url", mcp_url)

    [account_1] = await mcp_client.call_tools(security.create_token("a@vendor.fr", 1),
                                              [("keyword_search", {"query": "facture"})])
    [account_2] = await mcp_client.call_tools(security.create_token("b@vendor.fr", 2),
                                              [("keyword_search", {"query": "facture"})])

    assert {r["title"] for r in account_1["results"]} == {"Contestation de facture"}
    assert {r["title"] for r in account_2["results"]} <= {"Budget confidentiel", "Lancement"}


async def test_un_autre_client_peut_ouvrir_une_source_de_son_propre_compte(mcp_url, sample_data):
    """Ce que fait un client MCP externe (pas notre agent) : chercher, puis ouvrir la source."""
    async def search_then_open(session):
        found = await session.call_tool("keyword_search", {"query": "facture"})
        source_id = found.structuredContent["results"][0]["interaction_id"]
        return source_id, await session.call_tool("get_interaction", {"interaction_id": source_id})

    headers_1 = {"Authorization": f"Bearer {security.create_token('a@vendor.fr', 1)}"}
    source_id, full = await open_session(mcp_url, headers_1, search_then_open)
    assert full.structuredContent["title"] == "Contestation de facture"
    assert "FAC-2291" in full.structuredContent["body"]

    async def open_from_account_2(session):
        return await session.call_tool("get_interaction", {"interaction_id": source_id})

    headers_2 = {"Authorization": f"Bearer {security.create_token('b@vendor.fr', 2)}"}
    assert (await open_session(mcp_url, headers_2, open_from_account_2)).isError


async def test_les_recherches_tournent_en_parallele(mcp_url, monkeypatch):
    monkeypatch.setattr(settings, "mcp_url", mcp_url)

    async def slow_search(*args, **kwargs):  # chaque recherche prend 0,5 s
        await asyncio.sleep(0.5)
        return []

    monkeypatch.setattr(search, "keyword_search", slow_search)
    monkeypatch.setattr(search, "semantic_search", slow_search)
    monkeypatch.setattr(search, "list_interactions", slow_search)
    calls = [("keyword_search", {"query": "facture"}),
             ("semantic_search", {"query": "litige de facturation"}),
             ("list_interactions", {})]

    start = time.perf_counter()
    outputs = await mcp_client.call_tools(security.create_token("a@vendor.fr", 1), calls)
    elapsed = time.perf_counter() - start

    assert all(output == {"results": []} for output in outputs)
    assert elapsed < 1.2  # l'une après l'autre, il faudrait au moins 1,5 s
