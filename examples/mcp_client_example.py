"""Un AUTRE programme qui utilise les outils de recherche, sans passer par l'agent.

POURQUOI CET EXEMPLE ?
    Pour prouver l'intérêt de MCP : n'importe quel client MCP peut utiliser les outils avec
    le token d'un utilisateur, et le serveur MCP le limite quand même au compte de cet
    utilisateur. Ce script fait exactement ce que ferait Claude Desktop ou l'agent d'une
    autre équipe.

CE QU'IL FAIT
    1. se connecte à l'API pour obtenir un token
    2. ouvre une session MCP avec ce token
    3. liste les outils disponibles
    4. cherche par mots-clés
    5. ouvre le texte complet du premier résultat

UTILISATION (avec l'API et le serveur MCP lancés)
    python examples/mcp_client_example.py EMAIL MOT_DE_PASSE "mots à chercher"
"""

import asyncio
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# Les adresses peuvent être changées avec des variables d'environnement
API_URL = os.getenv("API_URL", "http://localhost:8000")
MCP_URL = os.getenv("MCP_URL", "http://localhost:8001/mcp")


async def main(email, password, query):
    # 1. Se connecter à l'API pour obtenir un token (le même login que l'interface)
    login = httpx.post(f"{API_URL}/login", json={"email": email, "password": password})
    login.raise_for_status()  # s'arrête avec une erreur si le login échoue (401...)
    token = login.json()["token"]

    # 2. Ouvrir une session MCP avec ce token dans les headers
    #    (même principe que agent/mcp_client.py : client HTTP -> transport MCP -> session)
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=60) as http:
        async with streamable_http_client(MCP_URL, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()  # poignée de main MCP obligatoire

                # 3. Lister les outils disponibles (nom + description + arguments)
                tools = await session.list_tools()
                print("Outils :", ", ".join(tool.name for tool in tools.tools))

                # 4. Chercher par mots-clés. Remarque : aucun account_id n'est envoyé,
                #    le serveur le lit dans le token.
                result = await session.call_tool("keyword_search", {"query": query, "limit": 3})
                results = result.structuredContent["results"]
                for r in results:
                    print(f"- {r['date']} {r['kind']} : {r['title']}")

                # 5. Ouvrir le texte complet du premier résultat grâce à son interaction_id
                if results:
                    full = await session.call_tool("get_interaction",
                                                   {"interaction_id": results[0]["interaction_id"]})
                    print("\nPremier résultat, texte complet :\n", full.structuredContent["body"][:500])


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit('usage : python examples/mcp_client_example.py EMAIL MOT_DE_PASSE "mots à chercher"')
    # *sys.argv[1:] : passe les 3 arguments (email, mot de passe, recherche) à main()
    asyncio.run(main(*sys.argv[1:]))
