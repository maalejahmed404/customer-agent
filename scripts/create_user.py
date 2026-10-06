"""Créer un utilisateur (ou changer son mot de passe), en ligne de commande.

Il n'y a pas de page d'inscription dans l'interface : les utilisateurs sont créés par
un administrateur avec ce script.

UTILISATION (depuis le dossier customer-agent/)
    python -m scripts.create_user EMAIL MOT_DE_PASSE ACCOUNT_ID
    Exemple : python -m scripts.create_user camille@vendor.fr mon-mot-de-passe 1

    Pour créer l'utilisateur dans MongoDB Atlas (Azure) plutôt qu'en local, définir
    d'abord la variable MONGO_URI (voir docs/DEPLOIEMENT.md, section 5).
"""

import asyncio
import sys

from api import users
from shared import database


async def main(email, password, account_id):
    await users.create_user(database.get_db(), email, password, account_id)
    print(f"L'utilisateur {email} peut se connecter au compte {account_id}")


if __name__ == "__main__":
    # sys.argv = ["scripts/create_user.py", EMAIL, MOT_DE_PASSE, ACCOUNT_ID] -> 4 éléments
    if len(sys.argv) != 4:
        # sys.exit avec un texte : l'affiche et arrête le programme avec un code d'erreur
        sys.exit("usage : python -m scripts.create_user EMAIL MOT_DE_PASSE ACCOUNT_ID")
    # int(...) : l'account_id est un nombre dans la base, pas un texte
    asyncio.run(main(sys.argv[1], sys.argv[2], int(sys.argv[3])))
