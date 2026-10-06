"""Nœud 1 — planner : décide QUOI chercher.

ENTRÉE (dans l'état)  : question, messages (la conversation)
SORTIE (renvoyée)     : plan, et remise à zéro de passages / sources / action_id

FONCTIONNEMENT
    Le LLM lit la question (et la conversation récente) et remplit un `Plan` :
    quelles recherches par mots-clés, quelles recherches par le sens, quels filtres,
    ou rien du tout (salutations, small talk).
    Si le LLM échoue, on ne bloque pas l'utilisateur : on cherche avec la question elle-même.

POURQUOI PLANIFIER AVANT DE CHERCHER ? (plutôt qu'un agent "ReAct" qui boucle)
    Un agent ReAct rappelle le LLM après chaque résultat d'outil : plus d'appels LLM et une
    durée imprévisible. Ici : 1 appel pour planifier, toutes les recherches en parallèle,
    1 appel pour répondre. Rapide, prévisible, et chaque étape se teste seule.
"""

import logging
from datetime import date

from agent import llm
from agent.prompts import PLAN_PROMPT, history_as_text
from agent.state import Plan, State

# Un "logger" par fichier : les messages indiquent de quel module ils viennent.
# Sur Azure, ils apparaissent dans les logs du conteneur "api".
log = logging.getLogger(__name__)


async def planner_node(state: State):
    question = state["question"]

    # 1. Construire le prompt : on remplit les {trous} de PLAN_PROMPT.
    prompt = PLAN_PROMPT.format(today=date.today(), history=history_as_text(state),
                                question=question)

    # 2. Demander le plan au LLM.
    try:
        # with_structured_output(Plan) : le LLM doit répondre en remplissant le "formulaire"
        # Plan. method="function_calling" : on utilise le mécanisme d'outils du modèle
        # (le plus fiable, et supporté par la plupart des modèles compatibles OpenAI).
        planner = llm.get_llm().with_structured_output(Plan, method="function_calling")
        plan = await planner.ainvoke(prompt)
        # Certains modèles renvoient None au lieu d'appeler l'outil : on le traite comme une erreur.
        if not isinstance(plan, Plan):
            raise ValueError("the model returned no plan")
    except Exception as exc:
        # 3. Plan de secours (LLM en panne, réponse invalide, timeout...) : on cherche avec
        #    la question telle quelle, par mots-clés ET par le sens. L'utilisateur a quand
        #    même une réponse, simplement moins bien ciblée.
        log.warning("Planner failed, searching with the question itself: %s", exc)
        plan = Plan(needs_data=True, keyword_queries=[question], semantic_queries=[question])

    # 4. Sécurité : le plan dit "il faut des données" mais ne propose AUCUNE recherche.
    #    Sans ce correctif, le retriever ne ferait rien et la réponse serait "rien trouvé".
    if plan.needs_data and not (plan.keyword_queries or plan.semantic_queries or plan.recent):
        plan.semantic_queries = [question]

    # 5. On renvoie le plan. On remet aussi à zéro les résultats de la question PRÉCÉDENTE :
    #    avec la mémoire (checkpointer), l'état de la conversation est conservé d'une question
    #    à l'autre ; sans cette remise à zéro, un email proposé à la question 1 serait
    #    renvoyé à nouveau à la question 2 (un test le vérifie).
    return {"plan": plan, "passages": [], "sources": [], "action_id": None}
