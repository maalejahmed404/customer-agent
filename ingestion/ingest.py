"""Ingestion des fichiers de comptes (data/accounts/*.json) dans MongoDB.

Chaque appel ou email est stocké une fois dans `interactions` (idempotence par empreinte
du contenu), puis découpé en chunks vectorisés reliés à leur interaction d'origine.

Usage : python -m ingestion.ingest [data/accounts | data/accounts/account_1.json]
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

from pymongo.errors import DuplicateKeyError

from ingestion.chunking import chunk_text
from shared import database, embeddings


def content_hash(account_id, kind, date, title, body):
    """Empreinte SHA-256 identifiant une interaction : même contenu, même empreinte."""
    raw = f"{account_id}|{kind}|{date}|{title}|{body}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def ingest_interaction(db, account_id, kind, date, title, body, summary=None):
    """Stocke une interaction et ses chunks. Renvoie False si elle était déjà stockée.

    `kind` vaut "call" ou "email" ; `summary` n'existe que pour les appels.
    """
    # Vérification avant le calcul des embeddings : pas d'appel Voyage pour un doublon.
    digest = content_hash(account_id, kind, date, title, body)
    if await db.interactions.find_one({"content_hash": digest}):
        return False

    # Le résumé forme son propre chunk, en tête : il répond bien aux questions générales.
    pieces = [f"Summary: {summary}"] if summary else []
    pieces += chunk_text(body)

    # Le titre préfixe chaque morceau pour lui redonner son contexte.
    vectors = await embeddings.embed([f"{title}\n{piece}" for piece in pieces])

    try:
        result = await db.interactions.insert_one({
            "account_id": account_id, "kind": kind, "date": date, "title": title,
            "body": body, "summary": summary, "content_hash": digest,
        })
    except DuplicateKeyError:
        # Ingestion concurrente : l'index unique sur content_hash a refusé le doublon.
        return False

    # account_id, kind, date et title sont dénormalisés dans chaque chunk pour filtrer
    # et afficher les résultats sans relire l'interaction.
    chunks = []
    for position, (piece, vector) in enumerate(zip(pieces, vectors)):
        chunks.append({
            "account_id": account_id,
            "interaction_id": result.inserted_id,
            "kind": kind, "date": date, "title": title,
            "position": position,   # 0 = résumé s'il existe
            "text": piece,
            "embedding": vector,
        })
    await db.chunks.insert_many(chunks)
    return True


async def ingest_file(db, path):
    """Charge un fichier de compte. Renvoie le nombre d'interactions nouvellement ajoutées."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    account_id = data["account_id"]

    await db.accounts.update_one({"_id": account_id},
                                 {"$set": {"name": data["account_name"]}}, upsert=True)

    added = 0
    for call in data.get("calls", []):
        added += await ingest_interaction(db, account_id, "call", call["date"], call["call_name"],
                                          call["transcript"], call.get("summary"))
    for email in data.get("emails", []):
        added += await ingest_interaction(db, account_id, "email", email["date"],
                                          email["subject"], email["content"])
    return added


async def main(location):
    """Ingère un fichier de compte, ou tous les .json d'un dossier."""
    location = Path(location)
    paths = [location] if location.is_file() else sorted(location.glob("*.json"))

    db = database.get_db()
    # L'index unique sur content_hash doit exister avant toute insertion.
    await database.create_indexes(db)

    for path in paths:
        added = await ingest_file(db, path)
        print(f"{path.name}: {added} nouvelles interactions")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "data/accounts"))
