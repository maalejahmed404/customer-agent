"""Nœud 3 — responder : écrit la réponse.

ENTRÉE (dans l'état)  : question, plan, passages, messages (la conversation)
SORTIE (renvoyée)     : answer, sources, messages (la question et la réponse, ajoutées à la mémoire)

FONCTIONNEMENT
    Le LLM répond UNIQUEMENT à partir des sources numérotées et les cite comme [1] ou [2][3].
    On lit ensuite les numéros cités dans la réponse pour renvoyer les sources correspondantes,
    chacune avec l'id de son appel ou email (l'interface peut alors ouvrir le document complet).
"""

import re

# HumanMessage = un message de l'utilisateur ; AIMessage = un message de l'assistant.
# Ce sont les objets que LangGraph stocke dans la mémoire de conversation.
from langchain_core.messages import AIMessage, HumanMessage

from agent import llm
from agent.prompts import ANSWER_PROMPT, format_sources
from agent.state import State, recent_history

NOTHING_FOUND = "Je n'ai rien trouvé à ce sujet dans les appels et les emails du compte."


def cited_numbers(answer, max_number):
    """Les numéros de sources cités dans la réponse. Ex. : "... [1][3] ... [1]" -> [1, 3].

    - re.findall(r"\\[(\\d+)\\]", ...) trouve tous les "[chiffres]" et renvoie les chiffres
    - le set {...} retire les doublons ([1] cité deux fois = une seule source)
    - on ignore les numéros impossibles (ex. [7] alors qu'il n'y a que 3 sources :
      le LLM s'est trompé, on ne va pas planter pour ça)
    - sorted : dans l'ordre croissant
    """
    numbers = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    return sorted(n for n in numbers if 1 <= n <= max_number)


async def responder_node(state: State):
    question = state["question"]
    passages = state.get("passages", [])

    # Cas 1 : il fallait des données mais la recherche n'a rien trouvé.
    #   -> pas besoin d'appeler le LLM (économie + aucun risque qu'il invente une réponse).
    #   On enregistre quand même la question et la réponse dans la mémoire.
    if state["plan"].needs_data and not passages:
        return {"answer": NOTHING_FOUND, "sources": [],
                "messages": [HumanMessage(question), AIMessage(NOTHING_FOUND)]}

    # Cas 2 : on a des sources -> elles vont dans le message UTILISATEUR (jamais dans le
    #   prompt système), numérotées et entourées de marqueurs "données non fiables".
    # Cas 3 : small talk ("Bonjour") -> la question seule.
    if passages:
        message = f"Sources:\n{format_sources(passages)}\n\nQuestion: {question}"
    else:
        message = question

    # Les messages envoyés au LLM, dans l'ordre :
    #   1. ("system", ANSWER_PROMPT)   : les règles
    #   2. *recent_history(state)      : les 6 derniers messages de la conversation
    #                                    (l'étoile "déplie" la liste dans la liste)
    #   3. ("human", message)          : les sources + la nouvelle question
    response = await llm.get_llm().ainvoke(
        [("system", ANSWER_PROMPT), *recent_history(state), ("human", message)])
    answer = response.content  # le texte de la réponse

    # Retrouver les sources citées. passages[n - 1] : la source [1] est à l'index 0.
    # {"number": n, **passage} : une copie du passage avec en plus son numéro de citation.
    sources = [{"number": n, **passages[n - 1]} for n in cited_numbers(answer, len(passages))]

    return {
        "answer": answer,
        "sources": sources,
        # On ne mémorise que la question et la réponse, PAS les sources : la mémoire reste
        # légère, et les extraits de clients ne s'accumulent pas dans les conversations.
        # (Grâce à add_messages, ces 2 messages sont AJOUTÉS à la conversation existante.)
        "messages": [HumanMessage(question), AIMessage(answer)],
    }
