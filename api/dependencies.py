"""Les "dépendances" FastAPI : du code lancé AVANT un endpoint, avec Depends(...).

C'EST QUOI UNE DÉPENDANCE ?
    Quand un endpoint déclare un paramètre `user=Depends(get_current_user)`, FastAPI :
      1. appelle get_current_user() avant l'endpoint (en lui donnant le header demandé),
      2. si elle lève une HTTPException (ex. 401), s'arrête là et renvoie l'erreur,
      3. sinon, passe sa valeur de retour à l'endpoint dans `user`.
    On écrit donc la vérification du token UNE fois, et chaque endpoint la réutilise.

CE FICHIER CONTIENT
    - get_current_user : lit le token JWT et renvoie l'utilisateur {"email", "account_id"}
    - get_agent        : renvoie l'agent LangGraph (créé une seule fois)

DANS LES TESTS
    On les remplace avec app.dependency_overrides[get_agent] = ... (voir tests/test_api.py) :
    pas besoin de vrai LLM ni de vraie base pour tester l'API.
"""

import jwt
from fastapi import Header, HTTPException
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

from agent.graph import build_graph
from shared import security
from shared.config import settings

# L'agent, créé au premier appel puis réutilisé (même principe que le client MongoDB).
_agent = None


def get_current_user(authorization: str = Header(default="")):
    """L'utilisateur et son compte viennent du token JWT, JAMAIS du corps de la requête.

    `authorization: str = Header(...)` : FastAPI lit automatiquement le header HTTP
    "Authorization" et le met dans ce paramètre ("" s'il est absent).
    """
    # Format attendu : "Bearer eyJhbGciOi..."
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token manquant")  # 401 = non authentifié
    try:
        # Vérifie la signature et l'expiration ; lève jwt.PyJWTError sinon
        payload = security.decode_token(authorization.removeprefix("Bearer "))
    except jwt.PyJWTError:
        raise HTTPException(401, "Token invalide ou expiré")
    # "sub" contient l'email (nom standard du champ "sujet" dans un JWT)
    return {"email": payload["sub"], "account_id": payload["account_id"]}


def get_agent():
    """L'agent LangGraph, avec la mémoire des conversations dans MongoDB. Créé au premier appel.

    POURQUOI UNE SEULE FOIS ?
        Construire le graphe et ouvrir la connexion MongoDB du checkpointer prend du temps :
        on le fait à la première question, puis toutes les questions réutilisent le même agent.
        L'agent n'a pas d'état propre à un utilisateur : chaque conversation est séparée par
        son thread_id (voir api/routes/chat.py), donc le partager est sans risque.
    """
    global _agent
    if _agent is None:
        # Le checkpointer sauvegarde l'état de chaque conversation dans MongoDB
        # (collections "checkpoints" et "checkpoint_writes").
        # Il utilise le client MongoDB SYNCHRONE (MongoClient), c'est ce qu'attend MongoDBSaver.
        # ttl : durée de vie en secondes -> MongoDB supprime automatiquement les conversations
        # après conversation_ttl_days jours (30 jours * 24 h * 3600 s). Les données clients ne
        # s'accumulent pas indéfiniment.
        checkpointer = MongoDBSaver(MongoClient(settings.mongo_uri), db_name=settings.db_name,
                                    ttl=settings.conversation_ttl_days * 24 * 3600)
        _agent = build_graph(checkpointer)
    return _agent
