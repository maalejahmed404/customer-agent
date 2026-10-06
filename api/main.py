"""Point d'entrée de l'API (FastAPI). L'agent LangGraph tourne DANS cette API.

OÙ ÇA TOURNE
    Sur Azure : Container App "api", port 8000, adresse https://api.internal.<domaine>
    En local  : uvicorn api.main:app --port 8000
    Documentation interactive (Swagger) : http://localhost:8000/docs  (générée par FastAPI)

ENDPOINTS
    GET  /health                        l'API répond ?                     (sans token)
    POST /login                         email + mot de passe -> token JWT  (sans token)
    POST /chat                          poser une question à l'agent
    GET  /interactions/{id}             texte complet d'un appel ou d'un email
    GET  /actions?status=pending        emails proposés par l'agent
    POST /actions/{id}/approve          approuver -> l'email est envoyé
    POST /actions/{id}/reject           refuser -> rien n'est envoyé

    Tous les endpoints sauf /health et /login demandent le header "Authorization: Bearer <token>".

ORGANISATION
    Ce fichier crée seulement l'application et "branche" les routes. Chaque groupe
    d'endpoints est dans son propre fichier (api/routes/*.py), sous forme d'un APIRouter.

Uvicorn (le serveur web) cherche la variable `app` dans ce module : "api.main:app".
"""

from fastapi import FastAPI

# Chaque module de routes contient un objet `router` avec ses endpoints
from api.routes import actions, chat, interactions, login

# L'application FastAPI. Le titre apparaît dans la documentation /docs.
app = FastAPI(title="Customer agent API")


# Endpoint de santé : pas de token, pas d'accès à la base. Répond dès que le serveur tourne.
# Utile pour vérifier un déploiement, et pour les sondes de santé d'Azure.
@app.get("/health")
async def health():
    # FastAPI transforme automatiquement le dict en réponse JSON
    return {"status": "ok"}


# "Brancher" les routes de chaque fichier sur l'application.
# Après ces lignes, /login, /chat, /interactions/... et /actions/... existent.
app.include_router(login.router)
app.include_router(chat.router)
app.include_router(interactions.router)
app.include_router(actions.router)
