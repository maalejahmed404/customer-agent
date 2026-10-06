"""Connexion à MongoDB et création des index.

Collections : accounts, interactions, chunks, users, actions, outbox, checkpoints (LangGraph).
"""

from pymongo import ASCENDING, DESCENDING, TEXT, AsyncMongoClient

from shared.config import settings

_client = None


def get_db():
    """Renvoie la base de données ; le client est partagé par tout le processus.

    Création paresseuse : le client asynchrone doit naître dans la boucle d'événements
    qui l'utilisera, laquelle n'existe pas encore à l'import.
    """
    global _client
    if _client is None:
        _client = AsyncMongoClient(settings.mongo_uri)
    return _client[settings.db_name]


async def create_indexes(db):
    """Crée les index nécessaires aux recherches. Idempotent."""
    # Unicité de l'empreinte : garantit l'idempotence de l'ingestion, y compris en concurrence.
    await db.interactions.create_index("content_hash", unique=True)

    # Sert list_interactions : filtre par compte, tri par date décroissante.
    await db.interactions.create_index([("account_id", ASCENDING), ("date", DESCENDING)])

    # Toutes les recherches filtrent par compte, parfois par type et par période.
    await db.chunks.create_index([("account_id", ASCENDING), ("kind", ASCENDING),
                                  ("date", DESCENDING)])

    # Index texte français (racinisation, mots vides) requis par keyword_search.
    # Une collection n'admet qu'un seul index texte, d'où le nom fixe.
    await db.chunks.create_index([("title", TEXT), ("text", TEXT)],
                                 default_language="french", name="chunks_text")

    # Liste des actions d'un compte par statut.
    await db.actions.create_index([("account_id", ASCENDING), ("status", ASCENDING)])
