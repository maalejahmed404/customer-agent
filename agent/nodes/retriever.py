"""Nœud 2 — retriever : exécute les recherches du plan.

ENTRÉE (dans l'état)  : plan, account_id, user_email
SORTIE (renvoyée)     : passages (les meilleurs extraits, triés, dans la limite de taille)

LES 4 ÉTAPES
    1. plan_to_calls : transforme le plan en liste d'appels d'outils MCP
    2. toutes les recherches partent EN MÊME TEMPS vers le serveur MCP (mcp_client.call_tools)
    3. fuse          : fusionne les listes de résultats (reciprocal rank fusion)
    4. fit_budget    : garde les meilleurs passages dans la limite de taille

POURQUOI MOTS-CLÉS **ET** SENS ?
    Les deux se trompent dans des cas différents :
      - mots-clés : trouve "FAC-2291" ou "Hôpital Manager" exactement, mais rate les synonymes,
      - sens      : trouve "problème de facturation" pour "facture contestée", mais peut
                    rater un numéro précis.
    Combiner les deux donne de meilleurs résultats que chacun seul.
"""

import logging

from agent import mcp_client
from agent.state import State
from shared import security
from shared.config import settings

log = logging.getLogger(__name__)

# Maximum 3 recherches de chaque type, même si le LLM en propose plus (limite la charge).
MAX_QUERIES_PER_TYPE = 3


def plan_to_calls(plan):
    """Un appel d'outil MCP par recherche du plan. Renvoie une liste de (nom_outil, arguments).

    Exemple : Plan(keyword_queries=["FAC-2291"], semantic_queries=["litige"], kind="email")
          ->  [("keyword_search",  {"query": "FAC-2291", "kind": "email"}),
               ("semantic_search", {"query": "litige",   "kind": "email"})]
    """
    # Les filtres communs à toutes les recherches du plan
    filters = {"kind": plan.kind, "date_from": plan.date_from, "date_to": plan.date_to}
    # On retire les filtres vides (None) : inutile de les envoyer au serveur.
    # (c'est une "dict comprehension" : on garde les paires clé/valeur dont la valeur existe)
    filters = {key: value for key, value in filters.items() if value}

    calls = []
    # [:3] : au plus 3 requêtes de chaque type
    for query in plan.keyword_queries[:MAX_QUERIES_PER_TYPE]:
        # {"query": query, **filters} : un nouveau dict avec "query" + tous les filtres
        calls.append(("keyword_search", {"query": query, **filters}))
    for query in plan.semantic_queries[:MAX_QUERIES_PER_TYPE]:
        calls.append(("semantic_search", {"query": query, **filters}))
    if plan.recent:
        # Les 5 derniers appels/emails (avec les mêmes filtres de type et de période)
        calls.append(("list_interactions", {**filters, "limit": 5}))
    return calls


def fuse(result_lists, k=60):
    """Reciprocal rank fusion (RRF) : fusionne plusieurs listes classées en une seule.

    PRINCIPE
        Dans chaque liste, un passage gagne 1 / (k + rang) points (rang 1 = le premier).
        On additionne les points de toutes les listes, puis on trie.
        Un passage trouvé par PLUSIEURS recherches cumule les points et passe devant.

    POURQUOI LE RANG ET PAS LE SCORE ?
        Le score de keyword_search (textScore MongoDB, ex. 2.3) et celui de semantic_search
        (cosinus, entre -1 et 1) n'ont pas la même échelle : impossible de les comparer.
        Le rang, lui, a le même sens partout.

    POURQUOI k = 60 ?
        Valeur standard de la littérature : elle adoucit l'écart entre le 1er et le 2e
        (1/61 vs 1/62) pour qu'un passage bien classé dans deux listes batte un passage
        premier dans une seule.

    Exemple : mots-clés = [a, b], sens = [c, b]
        a : 1/61            = 0.0164
        b : 1/62 + 1/62     = 0.0323   <- trouvé 2 fois, il passe premier
        c : 1/61            = 0.0164
        résultat : [b, a, c]
    """
    scores = {}    # id du passage -> total des points
    passages = {}  # id du passage -> le passage lui-même
    for results in result_lists:
        # enumerate donne rank = 0, 1, 2... d'où "rank + 1" pour avoir un rang à partir de 1
        for rank, passage in enumerate(results):
            passage_id = passage["id"]
            scores[passage_id] = scores.get(passage_id, 0) + 1 / (k + rank + 1)
            # setdefault : on garde la PREMIÈRE version vue du passage (évite les doublons)
            passages.setdefault(passage_id, passage)
    # Trier les ids par total de points, du plus grand au plus petit
    best_ids = sorted(scores, key=scores.get, reverse=True)
    return [passages[passage_id] for passage_id in best_ids]


def fit_budget(passages, max_chars):
    """Garde les passages dans l'ordre, tant que le total ne dépasse pas `max_chars`.

    Les passages sont déjà triés du meilleur au moins bon : on garde les meilleurs.
    Un passage trop long pour la place restante est sauté, mais on continue avec les
    suivants (un plus petit peut encore tenir).
    """
    kept = []
    used = 0  # nombre de caractères déjà utilisés
    for passage in passages:
        size = len(passage["text"])
        if used + size <= max_chars:
            kept.append(passage)
            used += size
    return kept


async def retriever_node(state: State):
    # 1. Le plan devient une liste d'appels d'outils
    calls = plan_to_calls(state["plan"])

    # 2. Un token pour le compte de l'utilisateur : le serveur MCP limite chaque recherche
    #    à ce compte. Il est créé ICI, à chaque fois, et jamais mis dans l'état : comme l'état
    #    est sauvegardé dans MongoDB (mémoire des conversations), aucun token n'y est stocké.
    token = security.create_token(state["user_email"], state["account_id"])

    # 3. Toutes les recherches en parallèle
    try:
        outputs = await mcp_client.call_tools(token, calls)
    except Exception as exc:
        # Le serveur MCP est injoignable (arrêté, mauvaise adresse...) : on continue sans
        # résultats. Le responder répondra "rien trouvé" plutôt que de faire planter l'API.
        log.error("MCP server unreachable: %s", exc)
        outputs = []

    # 4. Récupérer les listes de résultats, en ignorant les recherches en échec.
    #    zip() associe chaque appel à son résultat (même ordre, grâce à asyncio.gather).
    result_lists = []
    for (tool_name, _), output in zip(calls, outputs):
        if isinstance(output, Exception):
            # Une recherche a échoué (ex. Voyage indisponible pour semantic_search) :
            # les autres recherches restent utiles.
            log.warning("%s failed: %s", tool_name, output)
        else:
            result_lists.append(output["results"])

    # 5. Fusionner, trier, couper à la taille maximale (12 000 caractères par défaut)
    return {"passages": fit_budget(fuse(result_lists), settings.context_chars)}
