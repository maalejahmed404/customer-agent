"""Dépendances FastAPI partagées par les routes : utilisateur courant et agent LangGraph.

Les tests les remplacent via app.dependency_overrides (voir tests/test_api.py).
"""

import jwt
from fastapi import Header, HTTPException
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

from agent.graph import build_graph
from shared import security
from shared.config import settings

_agent = None


def get_current_user(authorization: str = Header(default="")):
    """Renvoie {"email", "account_id"} à partir du jeton Bearer ; 401 s'il est absent ou invalide.

    Le compte vient du jeton, jamais du corps de la requête.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token manquant")
    try:
        payload = security.decode_token(authorization.removeprefix("Bearer "))
    except jwt.PyJWTError:
        raise HTTPException(401, "Token invalide ou expiré")
    return {"email": payload["sub"], "account_id": payload["account_id"]}


def get_agent():
    """Renvoie l'agent LangGraph, construit au premier appel puis partagé.

    Le partage est sûr : l'agent ne porte aucun état utilisateur, les conversations
    sont séparées par thread_id (voir api/routes/chat.py).
    """
    global _agent
    if _agent is None:
        # MongoDBSaver attend le client synchrone. Le TTL purge les conversations
        # au bout de conversation_ttl_days jours.
        checkpointer = MongoDBSaver(MongoClient(settings.mongo_uri), db_name=settings.db_name,
                                    ttl=settings.conversation_ttl_days * 24 * 3600)
        _agent = build_graph(checkpointer)
    return _agent
