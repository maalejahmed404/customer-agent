"""Serveur MCP : expose les outils de recherche (lecture seule) en HTTP.

C'EST QUOI MCP ?
    MCP (Model Context Protocol) est un protocole standard pour donner des "outils" à un
    agent IA. Un serveur MCP annonce ses outils (nom, description, arguments) et un client
    MCP peut les lister puis les appeler. L'intérêt : N'IMPORTE QUEL client MCP (notre agent,
    Claude Desktop, MCP Inspector, l'agent d'une autre équipe...) peut utiliser ces outils
    sans qu'on écrive une API spéciale pour chacun.

OÙ ÇA TOURNE
    Sur Azure : Container App "mcp", port 8001, adresse https://mcp.internal.<domaine>/mcp
    En local  : python -m mcp_server.server   ->   http://localhost:8001/mcp

LES OUTILS
    keyword_search      recherche par mots-clés
    semantic_search     recherche par le sens (embeddings)
    list_interactions   derniers appels/emails
    get_interaction     texte complet d'un appel/email

SÉCURITÉ
    Aucun outil n'a d'argument "account_id". Chaque requête doit porter un token JWT
    (header Authorization: Bearer ...) et le compte est lu DANS le token (get_account_id).
    Un client ne peut donc jamais demander les données d'un autre compte.

Ce fichier est volontairement "mince" : chaque outil lit le compte dans le token puis
appelle la fonction correspondante de shared/search.py, où se trouve la vraie logique.
"""

from typing import Any

# FastMCP : la librairie qui transforme de simples fonctions Python en outils MCP.
# Context : un objet donné à chaque outil, qui permet d'accéder à la requête HTTP reçue.
from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from shared import database, embeddings, search, security
from shared.config import settings

# Nombre maximum de résultats par recherche, quoi que demande le client :
# évite qu'un client demande 10 000 résultats d'un coup.
MAX_RESULTS = 20

# Création du serveur.
#   host="0.0.0.0"        : écouter sur toutes les interfaces réseau (obligatoire dans un conteneur)
#   stateless_http=True   : chaque requête HTTP est indépendante, le serveur ne garde pas de
#                           session en mémoire -> on peut avoir plusieurs réplicas sur Azure et
#                           n'importe lequel peut répondre à n'importe quelle requête
#   json_response=True    : répondre en JSON simple (plutôt qu'en flux SSE)
mcp = FastMCP("account-memory", host="0.0.0.0", port=settings.mcp_port,
              stateless_http=True, json_response=True)


def get_account_id(ctx: Context):
    """Lit le compte dans le token JWT de la requête. C'est le SEUL endroit qui lit le token.

    Pour passer plus tard à Microsoft Entra ID, c'est cette fonction qu'il faudra changer.
    """
    # La requête HTTP d'origine (avec ses headers) est accessible via le contexte.
    request = ctx.request_context.request
    header = request.headers.get("authorization", "") if request else ""

    # Format attendu : "Bearer eyJhbGciOi..."
    if not header.startswith("Bearer "):
        # Une exception dans un outil est renvoyée au client comme une erreur d'outil.
        raise PermissionError("Missing bearer token")
    token = header.removeprefix("Bearer ")

    # decode_token vérifie la signature et l'expiration (lève une exception si invalide),
    # puis on lit account_id. int() : on s'assure que c'est bien un nombre.
    return int(security.decode_token(token)["account_id"])


# ---------------------------------------------------------------------- les outils
# @mcp.tool() enregistre la fonction comme outil MCP. FastMCP en déduit automatiquement :
#   - le NOM de l'outil          = le nom de la fonction
#   - la DESCRIPTION             = la docstring (lue par les clients MCP et par les LLM,
#                                  c'est pourquoi elle reste en anglais)
#   - les ARGUMENTS et leur type = les paramètres de la fonction (query: str, limit: int...)
# Le paramètre `ctx: Context` est spécial : il est rempli par FastMCP et n'apparaît PAS
# dans les arguments visibles par le client (un test le vérifie).
#
# Tous les outils sont "async" et utilisent des clients asynchrones (MongoDB, HTTP) :
# quand l'agent envoie 3 recherches en même temps, elles attendent la base EN PARALLÈLE.

@mcp.tool()
async def keyword_search(ctx: Context, query: str, kind: str = "any", date_from: str | None = None,
                         date_to: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Full-text search in the account's calls and emails (MongoDB text index, French).
    Best for exact words: names, products, amounts, invoice numbers.
    kind: "call", "email" or "any". Dates: YYYY-MM-DD."""
    account_id = get_account_id(ctx)  # 1. le compte vient du token
    # 2. la recherche, limitée à MAX_RESULTS résultats
    results = await search.keyword_search(database.get_db(), account_id, query, kind,
                                          date_from, date_to, min(limit, MAX_RESULTS))
    # 3. on renvoie un dict {"results": [...]} (un outil MCP renvoie un objet, pas une liste)
    return {"results": results}


@mcp.tool()
async def semantic_search(ctx: Context, query: str, kind: str = "any", date_from: str | None = None,
                          date_to: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Search the account's calls and emails by meaning (embeddings).
    Best for topics and questions phrased differently from the text.
    kind: "call", "email" or "any". Dates: YYYY-MM-DD."""
    account_id = get_account_id(ctx)
    # La question doit d'abord être transformée en vecteur (input_type="query").
    # embed() renvoie une liste de vecteurs ; on en a demandé un seul, d'où [vector] = ...
    [vector] = await embeddings.embed([query], input_type="query")
    results = await search.semantic_search(database.get_db(), account_id, vector, kind,
                                           date_from, date_to, min(limit, MAX_RESULTS))
    return {"results": results}


@mcp.tool()
async def list_interactions(ctx: Context, kind: str = "any", date_from: str | None = None,
                            date_to: str | None = None, limit: int = 10) -> dict[str, Any]:
    """The account's most recent calls and emails, newest first, with their summary.
    Best for "what happened lately" or "the last call"."""
    account_id = get_account_id(ctx)
    results = await search.list_interactions(database.get_db(), account_id, kind,
                                             date_from, date_to, min(limit, MAX_RESULTS))
    return {"results": results}


@mcp.tool()
async def get_interaction(ctx: Context, interaction_id: str) -> dict[str, Any]:
    """The full text of one call or email, from the interaction_id of a search result."""
    account_id = get_account_id(ctx)
    interaction = await search.get_interaction(database.get_db(), account_id, interaction_id)
    if interaction is None:
        # Même message que l'id existe dans un autre compte ou pas du tout :
        # on ne révèle pas l'existence de données d'autres comptes.
        raise ValueError("No call or email with this id in your account")
    return interaction


# ------------------------------------------------------------------ santé du serveur

# Une route HTTP classique (pas un outil MCP) : GET /health répond {"status": "ok"}.
# Sert à vérifier que le serveur tourne (tests manuels, sondes de santé Azure).
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request):
    return JSONResponse({"status": "ok"})


# Lancement quand on exécute "python -m mcp_server.server".
# "streamable-http" : le transport MCP par HTTP (le point d'entrée est /mcp).
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
