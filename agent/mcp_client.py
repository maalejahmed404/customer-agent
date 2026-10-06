"""Client MCP de l'agent : exécute les appels d'outils du retriever sur settings.mcp_url."""

import asyncio
import json

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from shared.config import settings


async def call_tools(token, calls):
    """Exécute en parallèle une liste de (nom_outil, arguments) sur une seule session MCP.

    Le token porte le compte de l'utilisateur : le serveur MCP y restreint chaque recherche.
    Renvoie une liste de même longueur et dans le même ordre, avec pour chaque appel
    son résultat ou l'exception levée.
    """
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers, timeout=60) as http:
        async with streamable_http_client(settings.mcp_url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tasks = [call_tool(session, name, args) for name, args in calls]

                # return_exceptions : un outil en échec n'annule pas les autres recherches.
                return await asyncio.gather(*tasks, return_exceptions=True)


async def call_tool(session, name, args):
    """Appelle un outil et renvoie son résultat ; lève RuntimeError si l'outil a échoué."""
    result = await session.call_tool(name, args)

    # Une erreur côté serveur revient comme un résultat isError, pas comme une exception.
    if result.isError:
        raise RuntimeError(f"{name} failed: {result.content[0].text}")

    if result.structuredContent is not None:
        return result.structuredContent
    # Repli : le résultat est aussi sérialisé en JSON dans content[0].
    return json.loads(result.content[0].text)
