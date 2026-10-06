"""Les utilisateurs (collection "users").

FORMAT D'UN UTILISATEUR
    {"_id": "camille@vendor.fr", "password_hash": "sel$empreinte", "account_id": 1}
    - l'_id est l'email en MINUSCULES : un email = un seul utilisateur, et la connexion
      marche quelle que soit la casse tapée ("Camille@Vendor.fr").
    - le mot de passe n'est jamais stocké, seulement son empreinte (shared/security.py).
    - account_id : le compte client auquel l'utilisateur a accès (mis dans son token au login).

QUI APPELLE CE FICHIER ?
    - api/routes/login.py       -> authenticate (à chaque connexion)
    - scripts/create_user.py    -> create_user  (en ligne de commande)
"""

from shared import security


async def create_user(db, email, password, account_id):
    """Crée un utilisateur, ou change son mot de passe (et son compte) s'il existe déjà."""
    await db.users.update_one(
        {"_id": email.lower()},
        {"$set": {"password_hash": security.hash_password(password), "account_id": account_id}},
        # upsert=True : "update or insert" -> met à jour s'il existe, sinon le crée
        upsert=True,
    )


async def authenticate(db, email, password):
    """Renvoie l'utilisateur si l'email et le mot de passe sont bons, sinon None.

    On renvoie None dans les DEUX cas (email inconnu OU mauvais mot de passe) : l'API
    répond le même message, ce qui ne révèle pas si un email existe.
    """
    user = await db.users.find_one({"_id": email.lower()})
    if user and security.verify_password(password, user["password_hash"]):
        return user
    return None
