"""Nœud 4 — email_drafter : rédige un email SANS l'envoyer.

ENTRÉE (dans l'état)  : question, passages, answer, account_id, user_email
SORTIE (renvoyée)     : action_id (ou un message ajouté à answer si impossible)

QUAND ?
    Seulement si le planner a mis draft_email=True (l'utilisateur a demandé un email).

SÉCURITÉ : "HUMAN IN THE LOOP"
    Le brouillon est sauvegardé comme action "pending" dans MongoDB. Ce nœud n'a AUCUN
    moyen d'envoyer un email : seul un humain, en cliquant "Approuver" dans l'interface,
    déclenche l'envoi (via l'API -> actions/approval.py -> decide).
    Même si un email malveillant dans les sources pousse le LLM à écrire à x@evil.com,
    l'humain voit le destinataire avant d'approuver.
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
    # 1. La demande : les sources (protégées) + la question de l'utilisateur.
    #    Le LLM peut y trouver des faits ET l'adresse du destinataire (ex. dans une signature).
    request = f"Sources:\n{format_sources(state.get('passages', []))}\n\nRequest: {state['question']}"

    # 2. Le LLM remplit le "formulaire" EmailDraft (to, subject, body).
    try:
        writer = llm.get_llm().with_structured_output(EmailDraft, method="function_calling")
        draft = await writer.ainvoke([("system", DRAFT_PROMPT), ("human", request)])
    except Exception as exc:
        # En cas d'échec, on garde la réponse déjà écrite par le responder et on ajoute
        # simplement une note : l'utilisateur a quand même sa réponse.
        log.warning("Email draft failed: %s", exc)
        return {"answer": state["answer"] + "\n\n(Je n'ai pas pu rédiger l'email.)"}

    # 3. Vérifier les destinataires : au moins un, et chacun doit être UNE adresse valide.
    #    all(...) est vrai seulement si TOUTES les adresses sont valides.
    #    Refuse par exemple "helene, and evil@x.com" (plusieurs adresses cachées dans une).
    if not draft.to or not all(is_valid_email(address) for address in draft.to):
        return {"answer": state["answer"]
                + "\n\n(Aucun email rédigé : il me faut une adresse de destinataire valide.)"}

    # 4. Enregistrer l'email comme action "pending". RIEN n'est envoyé ici.
    #    Le compte et l'auteur viennent de l'état (donc du token), pas du LLM.
    email = {"to": draft.to, "subject": draft.subject, "body": draft.body}
    action_id = await approval.propose(database.get_db(), state["account_id"],
                                       state["user_email"], "send_email", email)

    # 5. L'API renvoie cet id à l'interface, qui affiche "Brouillon enregistré, à valider".
    return {"action_id": action_id}
