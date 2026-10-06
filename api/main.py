"""Application FastAPI : expose /health et monte les routeurs de api/routes.

Toutes les routes exigent un jeton Bearer, sauf /health et /login.
"""

from fastapi import FastAPI

from api.routes import actions, chat, interactions, login

app = FastAPI(title="Customer agent API")


# Sans jeton ni accès à la base : sert aux sondes de santé d'Azure.
@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(login.router)
app.include_router(chat.router)
app.include_router(interactions.router)
app.include_router(actions.router)
