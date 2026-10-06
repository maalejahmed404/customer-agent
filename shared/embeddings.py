"""Embeddings (vecteurs de sens) avec l'API Voyage AI.

C'EST QUOI UN EMBEDDING ?
    Une liste de nombres (ici 256) qui représente le SENS d'un texte. Deux textes qui
    parlent de la même chose ont des vecteurs proches, même s'ils n'ont aucun mot en commun :
        "la facture est contestée"  ≈  "problème de facturation"
    C'est ce qui permet la recherche par le sens (shared/search.py -> semantic_search).

QUI APPELLE CE FICHIER ?
    - ingestion/ingest.py      : pour chaque chunk stocké      (input_type="document")
    - mcp_server/server.py     : pour chaque question cherchée (input_type="query")

POURQUOI DEUX input_type ?
    Voyage encode un peu différemment un document et une question : une question est
    courte et formulée autrement que le passage qui y répond. Le préciser améliore la recherche.
"""

import asyncio

import httpx  # client HTTP qui fonctionne en asynchrone (async/await)

from shared.config import settings

# Nombre maximum d'essais quand Voyage répond "trop de requêtes" (erreur 429).
MAX_ATTEMPTS = 6


async def embed(texts, input_type="document"):
    """Renvoie un vecteur par texte, dans le même ordre que `texts`.

    Exemple : await embed(["bonjour", "facture"])  ->  [[0.12, -0.03, ...], [0.44, 0.01, ...]]
    On envoie plusieurs textes dans UNE seule requête HTTP : beaucoup plus rapide
    (et moins de requêtes comptées dans la limite de Voyage) qu'un appel par texte.
    """
    # Le corps de la requête, au format attendu par l'API Voyage
    body = {
        "input": texts,
        "model": settings.embedding_model,
        "input_type": input_type,
        "output_dimension": settings.embedding_dimensions,  # 256 nombres par vecteur
    }
    # La clé API est envoyée dans le header "Authorization"
    headers = {"Authorization": f"Bearer {settings.voyage_api_key}"}

    # "async with" ouvre le client HTTP et le ferme proprement à la fin du bloc.
    # timeout=60 : on abandonne si Voyage ne répond pas en 60 secondes.
    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(MAX_ATTEMPTS):
            response = await client.post(settings.embedding_url, json=body, headers=headers)
            if response.status_code != 429:
                break  # pas limité : on sort de la boucle (succès OU autre erreur)
            # 429 = "Too Many Requests" : on a dépassé la limite de Voyage (3 requêtes/minute
            # sans moyen de paiement). On attend de plus en plus longtemps avant de réessayer
            # ("backoff exponentiel") : 5 s, 10 s, 20 s, 40 s, puis 60 s maximum.
            # asyncio.sleep attend SANS bloquer le reste du programme.
            await asyncio.sleep(min(60, 5 * 2 ** attempt))

    # Si la dernière réponse est une erreur (401 clé invalide, 500, 429 persistant...),
    # raise_for_status() lève une exception au lieu de continuer avec des données fausses.
    response.raise_for_status()

    # Réponse de Voyage : {"data": [{"embedding": [...]}, {"embedding": [...]}, ...]}
    # On ne garde que les listes de nombres, dans l'ordre.
    return [item["embedding"] for item in response.json()["data"]]
