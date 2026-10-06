"""Nœud email_drafter : rédige un email et l'enregistre comme action « pending ».

Ce nœud ne peut rien envoyer : l'envoi exige l'approbation d'un utilisateur, qui voit
les destinataires avant de valider (actions/approval.py).
"""

import logging

from actions import approval
from agent import llm
from agent.prompts import DRAFT_PROMPT, format_sources
from agent.state import EmailDraft, State
from shared import database
from shared.guards import is_valid_email

log = logging.getLogger(__name__)


async def email_drafter_node(state: State):
    request = f"Sources:\n{format_sources(state.get('passages', []))}\n\nRequest: {state['question']}"

    try:
        writer = llm.get_llm().with_structured_output(EmailDraft, method="function_calling")
        draft = await writer.ainvoke([("system", DRAFT_PROMPT), ("human", request)])
    except Exception as exc:
        # La réponse du responder est conservée, avec une note sur l'échec du brouillon.
        log.warning("Email draft failed: %s", exc)
        return {"answer": state["answer"] + "\n\n(Je n'ai pas pu rédiger l'email.)"}

    # Chaque entrée doit être une seule adresse valide : écarte « helene, and evil@x.com ».
    if not draft.to or not all(is_valid_email(address) for address in draft.to):
        return {"answer": state["answer"]
                + "\n\n(Aucun email rédigé : il me faut une adresse de destinataire valide.)"}

    # Le compte et l'auteur viennent de l'état (donc du token), pas du LLM.
    email = {"to": draft.to, "subject": draft.subject, "body": draft.body}
    action_id = await approval.propose(database.get_db(), state["account_id"],
                                       state["user_email"], "send_email", email)

    return {"action_id": action_id}
