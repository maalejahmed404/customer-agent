"""Connexion à MongoDB et création des index.

RÔLE
    - get_db()          : donner accès à la base de données (un seul client pour tout le programme)
    - create_indexes()  : créer les index dont les recherches ont besoin

COLLECTIONS UTILISÉES (une "collection" MongoDB = l'équivalent d'une table SQL)
    accounts       un document par compte client          (_id = account_id, name)
    interactions   un document par appel ou email          (account_id, kind, date, title, body...)
    chunks         morceaux de texte + embedding           (account_id, interaction_id, text...)
    users          utilisateurs qui peuvent se connecter   (_id = email, password_hash, account_id)
    actions        emails proposés par l'agent, en attente de validation humaine
    outbox         emails "envoyés" quand aucun serveur SMTP n'est configuré
    checkpoints    mémoire des conversations (écrite automatiquement par LangGraph)

    MongoDB crée une collection automatiquement au premier document inséré :
    il n'y a pas de "CREATE TABLE" à écrire.
"""

# ASCENDING / DESCENDING : sens de tri d'un index (1 / -1).
# TEXT : type d'index spécial pour la recherche plein texte ($text).
# AsyncMongoClient : le client MongoDB ASYNCHRONE (fonctionne avec async/await).
from pymongo import ASCENDING, DESCENDING, TEXT, AsyncMongoClient

from shared.config import settings

# Le client MongoDB, gardé dans une variable du module.
# Il vaut None tant que personne n'a appelé get_db().
_client = None


def get_db():
    """Renvoie la base de données. Le client MongoDB est créé une seule fois, au premier appel.

    POURQUOI UN SEUL CLIENT ?
        Un client MongoDB gère un "pool" de connexions réutilisables. En créer un à chaque
        requête serait lent et ouvrirait des centaines de connexions.

    POURQUOI LE CRÉER AU PREMIER APPEL (et pas à l'import du fichier) ?
        Le client asynchrone doit être créé à l'intérieur de la boucle d'événements (asyncio)
        qui l'utilisera. Au moment de l'import, cette boucle n'existe pas encore.

    Utilisation :  db = database.get_db()   puis   await db.users.find_one(...)
    """
    global _client  # "global" : on modifie la variable du module, pas une variable locale
    if _client is None:
        # La connexion réelle se fait au premier vrai appel à la base, pas ici.
        _client = AsyncMongoClient(settings.mongo_uri)
    # client["nom"] renvoie la base de données de ce nom
    return _client[settings.db_name]


async def create_indexes(db):
    """Crée les index. Sans effet s'ils existent déjà : on peut l'appeler à chaque ingestion.

    Un index, c'est comme l'index à la fin d'un livre : MongoDB trouve les documents sans
    avoir à les parcourir tous. Sans index, chaque recherche lirait toute la collection.
    Cette fonction est appelée par ingestion/ingest.py avant de charger les données.
    """
    # 1. Index UNIQUE sur l'empreinte du contenu : MongoDB REFUSE d'insérer deux
    #    interactions avec la même empreinte -> un appel/email n'est jamais stocké deux fois,
    #    même si on relance l'ingestion ou si deux ingestions tournent en même temps.
    await db.interactions.create_index("content_hash", unique=True)

    # 2. Index composé (compte, puis date décroissante) : sert à list_interactions
    #    ("les derniers appels/emails du compte X"), filtré par compte et trié par date.
    await db.interactions.create_index([("account_id", ASCENDING), ("date", DESCENDING)])

    # 3. Même idée pour les chunks : toutes les recherches filtrent par compte,
    #    parfois par type (appel/email) et par période.
    await db.chunks.create_index([("account_id", ASCENDING), ("kind", ASCENDING),
                                  ("date", DESCENDING)])

    # 4. Index TEXTE en français sur le titre et le texte des chunks.
    #    Obligatoire pour les requêtes {"$text": {"$search": ...}} de keyword_search.
    #    default_language="french" active :
    #      - la racinisation : "facture", "factures", "facturées" -> même racine
    #      - les mots vides : "le", "la", "de"... sont ignorés
    #    Une collection ne peut avoir qu'UN index texte : on lui donne un nom fixe.
    await db.chunks.create_index([("title", TEXT), ("text", TEXT)],
                                 default_language="french", name="chunks_text")

    # 5. Index pour lister rapidement les actions d'un compte par statut ("pending"...).
    await db.actions.create_index([("account_id", ASCENDING), ("status", ASCENDING)])
