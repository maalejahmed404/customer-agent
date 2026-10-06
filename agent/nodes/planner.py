"""Nœud planner : produit le plan de recherche à partir de la question et de l'historique.

Un seul appel LLM planifie, les recherches partent ensuite en parallèle : latence
prévisible, contrairement à une boucle ReAct.
"""

import logging
from datetime import date

from agent import llm
from agent.prompts import PLAN_PROMPT, history_as_text
from agent.state import Plan, State

log = logging.getLogger(__name__)


async def planner_node(state: State):
    question = state["question"]

    prompt = PLAN_PROMPT.format(today=date.today(), history=history_as_text(state),
                                question=question)

    try:
        planner = llm.get_llm().with_structured_output(Plan, method="function_calling")
        plan = await planner.ainvoke(prompt)
        # Certains modèles renvoient None au lieu d'appeler l'outil.
        if not isinstance(plan, Plan):
            raise ValueError("the model returned no plan")
    except Exception as exc:
        # Repli : recherche par mots-clés et sémantique avec la question brute.
        log.warning("Planner failed, searching with the question itself: %s", exc)
        plan = Plan(needs_data=True, keyword_queries=[question], semantic_queries=[question])

    # Un plan qui demande des données sans proposer de recherche laisserait le retriever à vide.
    if plan.needs_data and not (plan.keyword_queries or plan.semantic_queries or plan.recent):
        plan.semantic_queries = [question]

    # L'état persiste entre les questions (checkpointer) : on efface les résultats du tour
    # précédent, sinon un email déjà proposé serait renvoyé à nouveau.
    return {"plan": plan, "passages": [], "sources": [], "action_id": None}
