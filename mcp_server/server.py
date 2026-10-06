"""Serveur MCP : outils de recherche en lecture seule sur les appels et emails d'un compte.

Aucun outil ne prend d'account_id : le compte est lu dans le jeton Bearer de la requête.
La logique de recherche est dans shared/search.py.
"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from shared import database, embeddings, search, security
from shared.config import settings

# Plafond de résultats par recherche, quelle que soit la limite demandée par le client.
MAX_RESULTS = 20

# stateless_http : aucune session en mémoire, n'importe quel réplica peut répondre.
mcp = FastMCP("account-memory", host="0.0.0.0", port=settings.mcp_port,
              stateless_http=True, json_response=True)


def get_account_id(ctx: Context):
    """Renvoie l'account_id du jeton Bearer de la requête ; lève une exception s'il est invalide.

    Seul point de lecture du jeton : à adapter ici pour passer à Microsoft Entra ID.
    """
    request = ctx.request_context.request
    header = request.headers.get("authorization", "") if request else ""

    if not header.startswith("Bearer "):
        raise PermissionError("Missing bearer token")
    token = header.removeprefix("Bearer ")

    return int(security.decode_token(token)["account_id"])


# ---------------------------------------------------------------------- outils
# Les docstrings des outils sont les descriptions envoyées aux clients MCP (en anglais).
# `ctx` est injecté par FastMCP et n'apparaît pas dans les arguments exposés.

@mcp.tool()
async def keyword_search(ctx: Context, query: str, kind: str = "any", date_from: str | None = None,
                         date_to: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Full-text search in the account's calls and emails (MongoDB text index, French).
    Best for exact words: names, products, amounts, invoice numbers.
    kind: "call", "email" or "any". Dates: YYYY-MM-DD."""
    account_id = get_account_id(ctx)
    results = await search.keyword_search(database.get_db(), account_id, query, kind,
                                          date_from, date_to, min(limit, MAX_RESULTS))
    return {"results": results}


@mcp.tool()
async def semantic_search(ctx: Context, query: str, kind: str = "any", date_from: str | None = None,
                          date_to: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Search the account's calls and emails by meaning (embeddings).
    Best for topics and questions phrased differently from the text.
    kind: "call", "email" or "any". Dates: YYYY-MM-DD."""
    account_id = get_account_id(ctx)
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
        # Même erreur que l'id soit inconnu ou appartienne à un autre compte.
        raise ValueError("No call or email with this id in your account")
    return interaction


# ---------------------------------------------------------------------- santé

# Route HTTP hors MCP, pour les sondes de santé.
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request):
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
