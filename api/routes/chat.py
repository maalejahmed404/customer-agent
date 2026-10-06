"""POST /chat : exécute l'agent LangGraph sur une question et renvoie réponse, sources et action."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_agent, get_current_user
from api.schemas import ChatRequest
from shared.guards import clean_question

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat(body: ChatRequest, user=Depends(get_current_user), agent=Depends(get_agent)):
    try:
        question = clean_question(body.question)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    # Le thread_id inclut le compte et l'utilisateur : un conversation_id deviné
    # ne permet pas de reprendre la conversation de quelqu'un d'autre.
    thread_id = f"{user['account_id']}:{user['email']}:{body.conversation_id}"

    # account_id et user_email viennent du jeton, jamais du corps de la requête.
    try:
        result = await agent.ainvoke(
            {"question": question, "account_id": user["account_id"], "user_email": user["email"]},
            {"configurable": {"thread_id": thread_id}},
        )
    except Exception:
        # 502 : une dépendance (LLM, MCP, base) a échoué ; la trace reste dans les logs.
        log.exception("Agent failed")
        raise HTTPException(502, "L'assistant a échoué, merci de réessayer.")

    return {
        "answer": result["answer"],
        "sources": result.get("sources", []),
        "action_id": result.get("action_id"),
    }
