"""Nœud retriever : exécute les recherches du plan via MCP, fusionne et tronque les résultats.

Recherche hybride : les mots-clés retrouvent les identifiants exacts (FAC-2291), la
recherche sémantique couvre les reformulations.
"""

import logging

from agent import mcp_client
from agent.state import State
from shared import security
from shared.config import settings

log = logging.getLogger(__name__)

# Borne la charge, quel que soit le nombre de requêtes proposées par le LLM.
MAX_QUERIES_PER_TYPE = 3


def plan_to_calls(plan):
    """Traduit le plan en liste de (nom_outil, arguments), filtres du plan inclus."""
    filters = {"kind": plan.kind, "date_from": plan.date_from, "date_to": plan.date_to}
    filters = {key: value for key, value in filters.items() if value}

    calls = []
    for query in plan.keyword_queries[:MAX_QUERIES_PER_TYPE]:
        calls.append(("keyword_search", {"query": query, **filters}))
    for query in plan.semantic_queries[:MAX_QUERIES_PER_TYPE]:
        calls.append(("semantic_search", {"query": query, **filters}))
    if plan.recent:
        calls.append(("list_interactions", {**filters, "limit": 5}))
    return calls


def fuse(result_lists, k=60):
    """Fusionne des listes classées par reciprocal rank fusion : score = somme des 1 / (k + rang).

    Le rang est utilisé plutôt que le score, car textScore MongoDB et cosinus ne sont pas
    comparables. k=60 est la valeur usuelle : elle favorise un passage bien classé dans
    plusieurs listes face à un passage premier dans une seule.
    """
    scores = {}
    passages = {}
    for results in result_lists:
        for rank, passage in enumerate(results):
            passage_id = passage["id"]
            scores[passage_id] = scores.get(passage_id, 0) + 1 / (k + rank + 1)
            passages.setdefault(passage_id, passage)
    best_ids = sorted(scores, key=scores.get, reverse=True)
    return [passages[passage_id] for passage_id in best_ids]


def fit_budget(passages, max_chars):
    """Garde les passages, dans l'ordre, tant que le total tient dans `max_chars`.

    Un passage trop long pour la place restante est sauté sans arrêter le parcours :
    un passage plus court peut encore tenir.
    """
    kept = []
    used = 0
    for passage in passages:
        size = len(passage["text"])
        if used + size <= max_chars:
            kept.append(passage)
            used += size
    return kept


async def retriever_node(state: State):
    calls = plan_to_calls(state["plan"])

    # Token émis pour le compte de l'utilisateur : le serveur MCP y restreint chaque recherche.
    # Il n'est pas mis dans l'état, qui est persisté par le checkpointer.
    token = security.create_token(state["user_email"], state["account_id"])

    try:
        outputs = await mcp_client.call_tools(token, calls)
    except Exception as exc:
        # Serveur MCP injoignable : on continue sans résultat, le responder répond « rien trouvé ».
        log.error("MCP server unreachable: %s", exc)
        outputs = []

    # Les recherches en échec sont ignorées, les autres restent exploitables.
    result_lists = []
    for (tool_name, _), output in zip(calls, outputs):
        if isinstance(output, Exception):
            log.warning("%s failed: %s", tool_name, output)
        else:
            result_lists.append(output["results"])

    # Le contexte est plafonné (settings.context_chars) pour borner la taille du prompt.
    return {"passages": fit_budget(fuse(result_lists), settings.context_chars)}
