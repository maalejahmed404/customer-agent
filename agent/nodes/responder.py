"""Nœud responder : rédige la réponse à partir des sources numérotées et en extrait les citations."""

import re

from langchain_core.messages import AIMessage, HumanMessage

from agent import llm
from agent.prompts import ANSWER_PROMPT, format_sources
from agent.state import State, recent_history

NOTHING_FOUND = "Je n'ai rien trouvé à ce sujet dans les appels et les emails du compte."


def cited_numbers(answer, max_number):
    """Renvoie, triés et sans doublon, les numéros de sources cités dans la réponse.

    Les numéros hors de 1..max_number (citation inventée par le LLM) sont ignorés.
    """
    numbers = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    return sorted(n for n in numbers if 1 <= n <= max_number)


async def responder_node(state: State):
    question = state["question"]
    passages = state.get("passages", [])

    # Données attendues mais recherche vide : réponse fixe, sans appel LLM, pour ne rien inventer.
    if state["plan"].needs_data and not passages:
        return {"answer": NOTHING_FOUND, "sources": [],
                "messages": [HumanMessage(question), AIMessage(NOTHING_FOUND)]}

    # Les sources vont dans le message utilisateur, enveloppées comme données non fiables,
    # et non dans le prompt système.
    if passages:
        message = f"Sources:\n{format_sources(passages)}\n\nQuestion: {question}"
    else:
        message = question

    response = await llm.get_llm().ainvoke(
        [("system", ANSWER_PROMPT), *recent_history(state), ("human", message)])
    answer = response.content

    sources = [{"number": n, **passages[n - 1]} for n in cited_numbers(answer, len(passages))]

    return {
        "answer": answer,
        "sources": sources,
        # Seules la question et la réponse sont mémorisées : les extraits clients ne
        # s'accumulent pas dans l'historique.
        "messages": [HumanMessage(question), AIMessage(answer)],
    }
