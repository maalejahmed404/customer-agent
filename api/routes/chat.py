"""POST /chat : pose une question à l'agent LangGraph.

Exemple :
    requête  : POST /chat   header "Authorization: Bearer <token>"
               {"question": "Où en est la facture ?", "conversation_id": "a1b2c3"}
    réponse  : {"answer": "La facture est contestée [1].",
                "sources": [{"number": 1, "interaction_id": "...", "title": "...", ...}],
                "action_id": null}

C'est ICI que l'API lance l'agent : l'agent n'a pas de serveur à lui.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_agent, get_current_user
from api.schemas import ChatRequest
from shared.guards import clean_question

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


# Les dépendances sont exécutées AVANT la fonction, dans l'ordre :
#   user  = get_current_user(...)  -> 401 si le token est absent/invalide (l'agent n'est
#                                     alors même pas créé)
#   agent = get_agent()            -> l'agent LangGraph (créé une fois)
@router.post("/chat")
async def chat(body: ChatRequest, user=Depends(get_current_user), agent=Depends(get_agent)):
    # 1. Vérifier la question (vide, trop longue, caractères de contrôle).
    #    clean_question lève ValueError ; on la transforme en erreur HTTP 400 (mauvaise requête).
    try:
        question = clean_question(body.question)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    # 2. L'identifiant de la conversation pour le checkpointer ("thread_id").
    #    Il contient le compte ET l'utilisateur : si un autre utilisateur envoie le même
    #    conversation_id, il obtient un AUTRE thread_id, donc une autre conversation (vide).
    #    Personne ne peut lire ou continuer la conversation de quelqu'un d'autre.
    #    Exemple : "1:camille@vendor.fr:a1b2c3"
    thread_id = f"{user['account_id']}:{user['email']}:{body.conversation_id}"

    # 3. Lancer l'agent.
    #    - 1er argument : l'état de départ. account_id et user_email viennent du TOKEN (user),
    #      jamais du corps de la requête.
    #    - 2e argument : la configuration ; "thread_id" dit au checkpointer quelle
    #      conversation recharger et où sauvegarder la suite.
    #    ainvoke exécute tout le graphe (planner -> retriever -> responder -> ...) et renvoie
    #    l'état final.
    try:
        result = await agent.ainvoke(
            {"question": question, "account_id": user["account_id"], "user_email": user["email"]},
            {"configurable": {"thread_id": thread_id}},
        )
    except Exception:
        # Erreur imprévue (LLM injoignable, clé API invalide...). log.exception écrit toute
        # la trace de l'erreur dans les logs (visible sur Azure), et l'utilisateur reçoit un
        # message simple. 502 = "un service dont on dépend a échoué".
        log.exception("Agent failed")
        raise HTTPException(502, "L'assistant a échoué, merci de réessayer.")

    # 4. On ne renvoie que ce dont l'interface a besoin (pas tout l'état interne).
    return {
        "answer": result["answer"],
        "sources": result.get("sources", []),     # les sources citées, avec leur interaction_id
        "action_id": result.get("action_id"),     # un email en attente de validation, ou None
    }
