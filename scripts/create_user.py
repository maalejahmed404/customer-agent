"""Crée un utilisateur ou change son mot de passe (il n'existe pas de page d'inscription).

Usage : python -m scripts.create_user EMAIL MOT_DE_PASSE ACCOUNT_ID
La base ciblée est celle de MONGO_URI (voir docs/DEPLOIEMENT.md, section 5).
"""

import asyncio
import sys

from api import users
from shared import database


async def main(email, password, account_id):
    await users.create_user(database.get_db(), email, password, account_id)
    print(f"L'utilisateur {email} peut se connecter au compte {account_id}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage : python -m scripts.create_user EMAIL MOT_DE_PASSE ACCOUNT_ID")
    asyncio.run(main(sys.argv[1], sys.argv[2], int(sys.argv[3])))
