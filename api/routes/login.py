"""POST /login : vérifie l'email et le mot de passe, renvoie un token JWT.

Exemple :
    requête  : POST /login   {"email": "camille@vendor.fr", "password": "..."}
    réponse  : {"token": "eyJ...", "email": "camille@vendor.fr",
                "account_id": 1, "account_name": "Clinique Saint-Aubin"}

L'interface garde ce token et l'envoie ensuite dans chaque requête
(header "Authorization: Bearer <token>"). Il est valable 8 heures.
"""

from fastapi import APIRouter, HTTPException

from api import users
from api.schemas import LoginRequest
from shared import database, security

# Un "router" regroupe des endpoints ; il est branché sur l'app dans api/main.py.
# tags : le nom du groupe dans la documentation /docs.
router = APIRouter(tags=["login"])


@router.post("/login")
async def login(body: LoginRequest):
    db = database.get_db()

    # 1. Vérifier l'email et le mot de passe
    user = await users.authenticate(db, body.email, body.password)
    if user is None:
        # Même message pour "email inconnu" et "mauvais mot de passe" (voir api/users.py)
        raise HTTPException(401, "Email ou mot de passe incorrect")

    # 2. Récupérer le nom du compte, pour l'afficher dans l'interface
    account = await db.accounts.find_one({"_id": user["account_id"]})

    # 3. Créer le token : il contient l'email ET le compte de l'utilisateur.
    #    C'est ce token qui décidera ensuite de toutes les données accessibles.
    return {
        "token": security.create_token(user["_id"], user["account_id"]),
        "email": user["_id"],
        "account_id": user["account_id"],
        # Si le compte n'existe pas encore en base (données pas chargées), nom par défaut
        "account_name": account["name"] if account else f"Compte {user['account_id']}",
    }
