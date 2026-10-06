"""Requêtes de lecture MongoDB, utilisées par le serveur MCP et par l'API.

Chaque requête est filtrée par `account_id`, lequel provient toujours du jeton JWT.
Les recherches renvoient toutes le même format, pour pouvoir être fusionnées :
{"id", "interaction_id", "kind", "date", "title", "text", "score"}.
"""

import numpy as np
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import DESCENDING


def build_filters(account_id, kind=None, date_from=None, date_to=None):
    """Construit le filtre MongoDB commun à toutes les recherches."""
    # Le filtre de compte est toujours présent : c'est lui qui isole les clients.
    filters = {"account_id": account_id}

    # Toute autre valeur ("any", None) : appels et emails.
    if kind in ("call", "email"):
        filters["kind"] = kind

    # Dates stockées en "AAAA-MM-JJ" : l'ordre lexicographique est l'ordre chronologique.
    if date_from or date_to:
        filters["date"] = {}
        if date_from:
            filters["date"]["$gte"] = date_from
        if date_to:
            filters["date"]["$lte"] = date_to
    return filters


def to_result(chunk, score):
    """Convertit un chunk en résultat sérialisable en JSON, sans son embedding."""
    return {
        "id": str(chunk["_id"]),
        "interaction_id": str(chunk["interaction_id"]),
        "kind": chunk["kind"],
        "date": chunk["date"],
        "title": chunk["title"],
        "text": chunk["text"],
        "score": round(float(score), 4),
    }


async def keyword_search(db, account_id, query, kind=None, date_from=None, date_to=None, limit=8):
    """Recherche par mots-clés, triée par pertinence.

    Adaptée aux termes exacts (noms, montants, numéros de facture).
    Nécessite l'index texte créé par database.create_indexes().
    """
    filters = build_filters(account_id, kind, date_from, date_to)
    filters["$text"] = {"$search": query}

    projection = {"embedding": 0, "score": {"$meta": "textScore"}}

    cursor = (db.chunks.find(filters, projection)
              .sort([("score", {"$meta": "textScore"})])
              .limit(limit))

    return [to_result(chunk, chunk["score"]) async for chunk in cursor]


async def semantic_search(db, account_id, query_vector, kind=None, date_from=None, date_to=None,
                          limit=8):
    """Recherche sémantique : similarité cosinus entre `query_vector` et chaque chunk du compte.

    Calcul exact en mémoire, sans index vectoriel : un compte ne compte que quelques
    centaines de chunks. Au-delà de quelques dizaines de milliers, passer à Atlas Vector Search.
    """
    chunks = await db.chunks.find(build_filters(account_id, kind, date_from, date_to)).to_list()
    if not chunks:
        return []

    vectors = np.array([chunk["embedding"] for chunk in chunks])
    query = np.array(query_vector)

    # Le terme 1e-10 évite une division par zéro sur un vecteur nul.
    scores = vectors @ query / (np.linalg.norm(vectors, axis=1) * np.linalg.norm(query) + 1e-10)

    best = np.argsort(-scores)[:limit]
    return [to_result(chunks[i], scores[i]) for i in best]


async def list_interactions(db, account_id, kind=None, date_from=None, date_to=None, limit=10):
    """Renvoie les dernières interactions du compte, de la plus récente à la plus ancienne.

    Lit la collection `interactions` et non les chunks ; le score vaut toujours 0.
    """
    cursor = (db.interactions.find(build_filters(account_id, kind, date_from, date_to))
              .sort("date", DESCENDING)
              .limit(limit))
    return [{
        "id": str(doc["_id"]),
        "interaction_id": str(doc["_id"]),
        "kind": doc["kind"],
        "date": doc["date"],
        "title": doc["title"],
        # Les emails n'ont pas de résumé : on renvoie le début du corps.
        "text": doc.get("summary") or doc["body"][:500],
        "score": 0.0,
    } async for doc in cursor]


async def get_interaction(db, account_id, interaction_id):
    """Renvoie l'interaction complète, ou None si elle n'existe pas dans ce compte."""
    # Un identifiant mal formé est traité comme introuvable.
    try:
        _id = ObjectId(interaction_id)
    except (InvalidId, TypeError):
        return None

    # Filtre sur l'id et le compte : un id valide d'un autre compte ne renvoie rien.
    doc = await db.interactions.find_one({"_id": _id, "account_id": account_id},
                                         {"content_hash": 0})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc
