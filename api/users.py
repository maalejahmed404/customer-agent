"""Accès à la collection "users" : création et authentification.

Un document : {"_id": email en minuscules, "password_hash": "sel$empreinte", "account_id": int}.
"""

from shared import security


async def create_user(db, email, password, account_id):
    """Crée un utilisateur, ou change son mot de passe (et son compte) s'il existe déjà."""
    await db.users.update_one(
        {"_id": email.lower()},
        {"$set": {"password_hash": security.hash_password(password), "account_id": account_id}},
        upsert=True,
    )


async def authenticate(db, email, password):
    """Renvoie l'utilisateur si l'email et le mot de passe sont bons, sinon None.

    None dans les deux cas d'échec, pour ne pas révéler si un email existe.
    """
    user = await db.users.find_one({"_id": email.lower()})
    if user and security.verify_password(password, user["password_hash"]):
        return user
    return None
