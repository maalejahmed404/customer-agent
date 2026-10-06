"""Client MCP : l'agent appelle les outils du serveur MCP.

RÔLE
    Envoyer au serveur MCP (mcp_server/server.py) une liste d'appels d'outils, TOUS EN MÊME
    TEMPS, et renvoyer leurs résultats. Utilisé par le nœud retriever.

ADRESSE DU SERVEUR
    settings.mcp_url (variable MCP_URL)
    local : http://localhost:8001/mcp     Azure : https://mcp.internal.<domaine>/mcp

LES 3 COUCHES DE CONNEXION (de l'extérieur vers l'intérieur)
    1. httpx.AsyncClient        : le client HTTP, avec le token dans ses headers
    2. streamable_http_client   : le "transport" MCP par HTTP (donne un canal lecture/écriture)
    3. ClientSession            : la session MCP (initialize, list_tools, call_tool...)
    Chaque couche est ouverte avec "async with" : elle est refermée proprement à la fin,
    même en cas d'erreur.
"""

import asyncio
import json

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from shared.config import settings


async def call_tools(token, calls):
    """Lance plusieurs appels d'outils EN PARALLÈLE, sur une seule session MCP.

    Paramètres :
        token : un token JWT du compte de l'utilisateur. Il est envoyé au serveur MCP, qui
                limite chaque recherche à ce compte.
        calls : liste de (nom_outil, arguments), par exemple
                [("keyword_search", {"query": "FAC-2291"}),
                 ("semantic_search", {"query": "litige facture"})]

    Renvoie une liste de même longueur, dans le même ordre : pour chaque appel, le
    résultat de l'outil ({"results": [...]}), ou l'exception s'il a échoué.
    """
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers, timeout=60) as http:
        # read / write : les deux canaux de communication avec le serveur ;
        # "_" : une 3e valeur renvoyée dont on n'a pas besoin.
        async with streamable_http_client(settings.mcp_url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                # Première étape obligatoire du protocole MCP : la "poignée de main"
                # (client et serveur échangent leurs versions et capacités).
                await session.initialize()

                # On prépare une "tâche" par appel. Rien n'est encore envoyé : ce sont des
                # coroutines (des appels async en attente).
                tasks = [call_tool(session, name, args) for name, args in calls]

                # asyncio.gather lance toutes les tâches EN MÊME TEMPS et attend qu'elles
                # soient toutes finies. 3 recherches de 0,5 s -> ~0,5 s au total, pas 1,5 s
                # (un test le vérifie).
                # return_exceptions=True : si une recherche échoue, gather ne s'arrête pas ;
                # il met l'exception à sa place dans la liste. Les autres résultats restent
                # utilisables (le retriever ignore simplement l'appel en échec).
                return await asyncio.gather(*tasks, return_exceptions=True)


async def call_tool(session, name, args):
    """Appelle UN outil et renvoie son résultat sous forme de dict Python."""
    result = await session.call_tool(name, args)

    # Si l'outil a levé une exception côté serveur (token invalide, id introuvable...),
    # MCP ne lève pas d'erreur côté client : il renvoie un résultat avec isError=True.
    # On le transforme en exception pour que ce soit visible (et traité par gather).
    if result.isError:
        raise RuntimeError(f"{name} failed: {result.content[0].text}")

    # Les outils renvoient un dict : MCP le transmet dans structuredContent.
    if result.structuredContent is not None:
        return result.structuredContent
    # Solution de repli : le résultat est aussi présent en texte JSON dans content[0].
    return json.loads(result.content[0].text)
