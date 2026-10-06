"""POST /login : vérifie email et mot de passe, renvoie un jeton JWT et le compte associé."""

from fastapi import APIRouter, HTTPException

from api import users
from api.schemas import LoginRequest
from shared import database, security

router = APIRouter(tags=["login"])


@router.post("/login")
async def login(body: LoginRequest):
    db = database.get_db()

    user = await users.authenticate(db, body.email, body.password)
    if user is None:
        # Même message pour un email inconnu et un mauvais mot de passe.
        raise HTTPException(401, "Email ou mot de passe incorrect")

    account = await db.accounts.find_one({"_id": user["account_id"]})

    # Le jeton porte l'account_id : il délimite ensuite toutes les données accessibles.
    return {
        "token": security.create_token(user["_id"], user["account_id"]),
        "email": user["_id"],
        "account_id": user["account_id"],
        # Nom par défaut si le compte n'est pas encore chargé en base.
        "account_name": account["name"] if account else f"Compte {user['account_id']}",
    }
