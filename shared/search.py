"""Les requêtes de lecture dans MongoDB (utilisées par le serveur MCP et par l'API).

RÔLE
    Les 4 façons de lire les données d'un compte :
        keyword_search     recherche par mots-clés        (index texte MongoDB)
        semantic_search    recherche par le sens          (embeddings + similarité cosinus)
        list_interactions  les derniers appels/emails     (tri par date)
        get_interaction    le texte complet d'un appel/email

    Le serveur MCP (mcp_server/server.py) expose les 4 comme "outils".
    L'API (api/routes/interactions.py) utilise get_interaction pour le bouton "voir la source".

RÈGLE D'OR : chaque requête commence par le filtre `account_id`.
    Un utilisateur ne peut donc JAMAIS lire les données d'un autre compte.
    Et l'account_id donné à ces fonctions vient toujours du token JWT, jamais de l'utilisateur.

FORMAT D'UN RÉSULTAT (le même pour les 3 recherches, pour pouvoir les fusionner ensuite)
    {"id", "interaction_id", "kind", "date", "title", "text", "score"}
    `interaction_id` est le lien vers l'appel ou l'email d'origine : c'est ce qui permet
    de citer ses sources et d'ouvrir le document complet.
"""

import numpy as np  # calcul vectoriel rapide (pour la similarité cosinus)
from bson import ObjectId  # le type des identifiants "_id" de MongoDB
from bson.errors import InvalidId  # erreur levée si une chaîne n'est pas un ObjectId valide
from pymongo import DESCENDING


def build_filters(account_id, kind=None, date_from=None, date_to=None):
    """Construit le filtre MongoDB commun à toutes les recherches.

    Exemple : build_filters(1, "email", "2025-01-01", None)
          ->  {"account_id": 1, "kind": "email", "date": {"$gte": "2025-01-01"}}
    """
    # Le filtre du compte est TOUJOURS présent : c'est lui qui isole les clients entre eux.
    filters = {"account_id": account_id}

    # Filtre sur le type : seulement si on demande "call" ou "email".
    # "any" (ou None) = pas de filtre = appels ET emails.
    if kind in ("call", "email"):
        filters["kind"] = kind

    # Filtre sur la période. Les dates sont stockées en texte "AAAA-MM-JJ" : dans ce
    # format, l'ordre alphabétique est aussi l'ordre chronologique, donc $gte / $lte
    # (plus grand ou égal / plus petit ou égal) fonctionnent directement sur du texte.
    if date_from or date_to:
        filters["date"] = {}
        if date_from:
            filters["date"]["$gte"] = date_from
        if date_to:
            filters["date"]["$lte"] = date_to
    return filters


def to_result(chunk, score):
    """Transforme un chunk MongoDB en résultat de recherche.

    - On convertit les ObjectId en texte (str) : ils ne passent pas tels quels en JSON.
    - On ne renvoie PAS l'embedding (256 nombres inutiles pour le client).
    - On arrondit le score à 4 décimales et on le convertit en float Python
      (numpy renvoie des types numpy que JSON ne sait pas écrire).
    """
    return {
        "id": str(chunk["_id"]),                         # id du chunk (sert à la fusion)
        "interaction_id": str(chunk["interaction_id"]),  # id de l'appel/email d'origine
        "kind": chunk["kind"],
        "date": chunk["date"],
        "title": chunk["title"],
        "text": chunk["text"],
        "score": round(float(score), 4),
    }


async def keyword_search(db, account_id, query, kind=None, date_from=None, date_to=None, limit=8):
    """Recherche par mots-clés (index texte MongoDB).

    Idéale pour les mots exacts : noms, produits, montants, numéros de facture ("FAC-2291").
    Nécessite l'index texte créé par database.create_indexes().
    """
    filters = build_filters(account_id, kind, date_from, date_to)
    # $text : utilise l'index texte. MongoDB découpe `query` en mots, les racinise
    # (en français) et trouve les chunks qui contiennent au moins un de ces mots.
    filters["$text"] = {"$search": query}

    # La "projection" choisit les champs renvoyés :
    #   "embedding": 0                       -> ne pas renvoyer l'embedding (lourd, inutile ici)
    #   "score": {"$meta": "textScore"}      -> ajouter un champ "score" = pertinence calculée
    #                                           par MongoDB (plus de mots trouvés = score plus haut)
    projection = {"embedding": 0, "score": {"$meta": "textScore"}}

    # find() ne lit rien tout de suite : il prépare un "curseur".
    # .sort(...)  : trier par pertinence (meilleur score d'abord)
    # .limit(...) : ne garder que les `limit` meilleurs
    cursor = (db.chunks.find(filters, projection)
              .sort([("score", {"$meta": "textScore"})])
              .limit(limit))

    # "async for" lit les documents un par un depuis MongoDB (sans bloquer le programme).
    return [to_result(chunk, chunk["score"]) async for chunk in cursor]


async def semantic_search(db, account_id, query_vector, kind=None, date_from=None, date_to=None,
                          limit=8):
    """Recherche par le sens : similarité cosinus entre la question et chaque chunk du compte.

    `query_vector` est l'embedding de la question (calculé par le serveur MCP avec Voyage AI).
    Idéale quand l'utilisateur n'emploie pas les mêmes mots que le texte :
    "problème de facturation" trouve "la facture est contestée".

    POURQUOI PAS D'INDEX VECTORIEL ?
        Un compte a quelques centaines de chunks : un calcul exact avec numpy prend
        quelques millisecondes. Pour de très gros comptes (dizaines de milliers de chunks),
        c'est la seule fonction à changer (Atlas Vector Search).
    """
    # 1. Charger TOUS les chunks du compte (avec les filtres), embeddings compris.
    #    .to_list() lit tout le curseur d'un coup et renvoie une liste Python.
    chunks = await db.chunks.find(build_filters(account_id, kind, date_from, date_to)).to_list()
    if not chunks:
        return []

    # 2. Mettre les vecteurs dans des tableaux numpy.
    #    vectors : une ligne par chunk, 256 colonnes  -> forme (nombre_de_chunks, 256)
    #    query   : un seul vecteur de 256 nombres     -> forme (256,)
    vectors = np.array([chunk["embedding"] for chunk in chunks])
    query = np.array(query_vector)

    # 3. Similarité cosinus pour TOUS les chunks en une seule opération :
    #       cos(A, B) = (A · B) / (|A| * |B|)
    #    - vectors @ query                      : produit scalaire de chaque chunk avec la question
    #    - np.linalg.norm(vectors, axis=1)      : la longueur de chaque vecteur chunk
    #    - np.linalg.norm(query)                : la longueur du vecteur question
    #    - + 1e-10                              : évite une division par zéro (vecteur nul)
    #    Résultat : un score entre -1 et 1 par chunk (1 = même sens).
    scores = vectors @ query / (np.linalg.norm(vectors, axis=1) * np.linalg.norm(query) + 1e-10)

    # 4. Trier : np.argsort trie du plus petit au plus grand, donc on trie -scores pour
    #    avoir les meilleurs d'abord. On obtient des INDICES (positions dans `chunks`).
    #    [:limit] garde les `limit` premiers.
    best = np.argsort(-scores)[:limit]
    return [to_result(chunks[i], scores[i]) for i in best]


async def list_interactions(db, account_id, kind=None, date_from=None, date_to=None, limit=10):
    """Les derniers appels/emails du compte (du plus récent au plus ancien), avec leur résumé.

    Utile pour "que s'est-il passé récemment ?" ou "le dernier appel".
    Ici on lit la collection `interactions` (documents entiers), pas les chunks.
    """
    cursor = (db.interactions.find(build_filters(account_id, kind, date_from, date_to))
              .sort("date", DESCENDING)   # le plus récent d'abord
              .limit(limit))
    # On renvoie le MÊME format que les recherches, pour pouvoir fusionner les résultats.
    return [{
        "id": str(doc["_id"]),
        "interaction_id": str(doc["_id"]),  # ici le résultat EST l'interaction elle-même
        "kind": doc["kind"],
        "date": doc["date"],
        "title": doc["title"],
        # Un appel a un résumé ; un email n'en a pas -> on prend ses 500 premiers caractères.
        # `a or b` renvoie b si a est vide ou None.
        "text": doc.get("summary") or doc["body"][:500],
        "score": 0.0,  # pas de notion de pertinence ici : c'est un simple tri par date
    } async for doc in cursor]


async def get_interaction(db, account_id, interaction_id):
    """Le texte complet d'un appel ou d'un email. None s'il n'existe pas dans CE compte."""
    # L'id arrive en texte (depuis l'URL ou l'outil MCP). On le convertit en ObjectId.
    # Si ce n'est pas un id valide (ex. "abc"), on répond "introuvable" au lieu de planter.
    try:
        _id = ObjectId(interaction_id)
    except (InvalidId, TypeError):
        return None

    # On cherche par id ET par compte : un id valide d'un AUTRE compte ne renvoie rien.
    # {"content_hash": 0} : on ne renvoie pas l'empreinte (détail interne).
    doc = await db.interactions.find_one({"_id": _id, "account_id": account_id},
                                         {"content_hash": 0})
    if doc:
        # Renommer "_id" (ObjectId) en "id" (texte) pour que le résultat passe en JSON.
        # pop() retire la clé "_id" et renvoie sa valeur.
        doc["id"] = str(doc.pop("_id"))
    return doc
