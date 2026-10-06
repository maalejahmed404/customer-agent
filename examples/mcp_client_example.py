"""Client MCP autonome : interroge les outils de recherche sans passer par l'agent.

Montre que n'importe quel client MCP muni du jeton d'un utilisateur reste limité au compte de ce jeton.

Usage : python examples/mcp_client_example.py EMAIL MOT_DE_PASSE "mots à chercher"
"""

import asyncio
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

API_URL = os.getenv("API_URL", "http://localhost:8000")
MCP_URL = os.getenv("MCP_URL", "http://localhost:8001/mcp")


async def main(email, password, query):
    login = httpx.post(f"{API_URL}/login", json={"email": email, "password": password})
    login.raise_for_status()
    token = login.json()["token"]

    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=60) as http:
        async with streamable_http_client(MCP_URL, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                print("Outils :", ", ".join(tool.name for tool in tools.tools))

                # Aucun account_id n'est envoyé : le serveur le lit dans le jeton.
                result = await session.call_tool("keyword_search", {"query": query, "limit": 3})
                results = result.structuredContent["results"]
                for r in results:
                    print(f"- {r['date']} {r['kind']} : {r['title']}")

                if results:
                    full = await session.call_tool("get_interaction",
                                                   {"interaction_id": results[0]["interaction_id"]})
                    print("\nPremier résultat, texte complet :\n", full.structuredContent["body"][:500])


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit('usage : python examples/mcp_client_example.py EMAIL MOT_DE_PASSE "mots à chercher"')
    asyncio.run(main(*sys.argv[1:]))
