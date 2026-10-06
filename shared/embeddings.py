"""Calcul des embeddings via l'API Voyage AI.

Voyage encode différemment un passage et une requête : l'ingestion utilise
input_type="document", la recherche input_type="query".
"""

import asyncio

import httpx

from shared.config import settings

# Nombre maximal d'essais sur une réponse 429.
MAX_ATTEMPTS = 6


async def embed(texts, input_type="document"):
    """Renvoie un vecteur par texte, dans l'ordre de `texts`, en une seule requête HTTP.

    Lève httpx.HTTPStatusError si la dernière réponse est une erreur (429 persistant compris).
    """
    body = {
        "input": texts,
        "model": settings.embedding_model,
        "input_type": input_type,
        "output_dimension": settings.embedding_dimensions,
    }
    headers = {"Authorization": f"Bearer {settings.voyage_api_key}"}

    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(MAX_ATTEMPTS):
            response = await client.post(settings.embedding_url, json=body, headers=headers)
            if response.status_code != 429:
                break
            # Limite de débit Voyage (3 requêtes/minute sans moyen de paiement) :
            # backoff exponentiel de 5 s, plafonné à 60 s.
            await asyncio.sleep(min(60, 5 * 2 ** attempt))

    response.raise_for_status()

    return [item["embedding"] for item in response.json()["data"]]
