"""Charger les fichiers des comptes (data/accounts/*.json) dans MongoDB.

RÔLE
    Transformer les appels et emails bruts en "mémoire du compte" interrogeable.

POUR CHAQUE APPEL OU EMAIL
    1. on le stocke UNE fois dans `interactions` (une empreinte du contenu évite les doublons :
       on peut relancer l'ingestion autant de fois qu'on veut)
    2. on le découpe en chunks (le résumé d'un appel devient son propre chunk)
    3. on calcule l'embedding de chaque chunk (Voyage AI)
    4. on stocke les chunks dans `chunks`, chacun avec le lien vers son interaction d'origine

FORMAT D'UN FICHIER DE COMPTE (data/accounts/account_1.json)
    {
      "account_id": 1,
      "account_name": "Clinique Saint-Aubin",
      "calls":  [{"date", "call_name", "transcript", "summary", ...}, ...],
      "emails": [{"date", "subject", "content"}, ...]
    }

UTILISATION
    python -m ingestion.ingest data/accounts                  (tous les comptes)
    python -m ingestion.ingest data/accounts/account_1.json   (un seul compte)
    Sur Azure, c'est le Job "ingest" qui lance cette commande (voir infra/main.bicep).
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

# Erreur levée par MongoDB quand on viole un index unique (ici : content_hash déjà présent).
from pymongo.errors import DuplicateKeyError

from ingestion.chunking import chunk_text
from shared import database, embeddings


def content_hash(account_id, kind, date, title, body):
    """Empreinte unique d'un appel/email : même contenu = même empreinte.

    On colle les champs qui identifient l'interaction ("1|email|2025-03-10|Titre|Texte...")
    puis on calcule leur SHA-256 : une chaîne de 64 caractères hexadécimaux.
    Si on ré-ingère le même email, on obtient la même empreinte -> on sait qu'il est déjà là.
    """
    raw = f"{account_id}|{kind}|{date}|{title}|{body}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def ingest_interaction(db, account_id, kind, date, title, body, summary=None):
    """Stocke un appel ou un email et ses chunks. Renvoie True si ajouté, False s'il était déjà stocké.

    kind    : "call" ou "email"
    title   : le nom de l'appel ou l'objet de l'email
    body    : la transcription de l'appel ou le texte de l'email
    summary : le résumé de l'appel (les emails n'en ont pas)
    """
    # 1. Déjà stocké ? On vérifie AVANT de calculer les embeddings : un appel à Voyage
    #    coûte du temps (et de l'argent), inutile de le faire pour un doublon.
    digest = content_hash(account_id, kind, date, title, body)
    if await db.interactions.find_one({"content_hash": digest}):
        return False

    # 2. Les morceaux de texte à rendre cherchables :
    #    - le résumé en premier (s'il existe) : c'est un excellent "chunk" car il condense
    #      tout l'appel, parfait pour les questions générales ("de quoi a-t-on parlé ?"),
    #    - puis le corps découpé en morceaux.
    pieces = [f"Summary: {summary}"] if summary else []
    pieces += chunk_text(body)

    # 3. Un embedding par morceau, en UN seul appel à Voyage.
    #    On ajoute le titre devant chaque morceau : un morceau isolé peut manquer de
    #    contexte ("il a dit oui"), le titre ("Négociation tarifaire") l'aide.
    vectors = await embeddings.embed([f"{title}\n{piece}" for piece in pieces])

    # 4. Stocker l'interaction complète.
    try:
        result = await db.interactions.insert_one({
            "account_id": account_id, "kind": kind, "date": date, "title": title,
            "body": body, "summary": summary, "content_hash": digest,
        })
    except DuplicateKeyError:
        # Cas rare : une autre ingestion lancée en même temps a stocké la même interaction
        # entre notre vérification (étape 1) et maintenant. L'index unique sur content_hash
        # a refusé l'insertion : pas de doublon, on s'arrête là.
        return False

    # 5. Stocker les chunks. `result.inserted_id` est l'_id MongoDB de l'interaction
    #    qu'on vient de créer : chaque chunk garde ce lien vers sa source.
    #    On copie aussi account_id, kind, date, title dans chaque chunk pour pouvoir
    #    filtrer et afficher les résultats sans relire l'interaction.
    chunks = []
    # zip() associe chaque morceau à son vecteur ; enumerate() donne la position 0, 1, 2...
    for position, (piece, vector) in enumerate(zip(pieces, vectors)):
        chunks.append({
            "account_id": account_id,
            "interaction_id": result.inserted_id,  # le lien vers la source
            "kind": kind, "date": date, "title": title,
            "position": position,   # ordre du morceau dans l'interaction (0 = résumé s'il existe)
            "text": piece,
            "embedding": vector,    # les 256 nombres
        })
    # insert_many : une seule requête pour tous les chunks (plus rapide qu'un insert par chunk)
    await db.chunks.insert_many(chunks)
    return True


async def ingest_file(db, path):
    """Charge un fichier de compte. Renvoie le nombre de NOUVELLES interactions ajoutées."""
    # Lire le fichier JSON (en UTF-8 : le texte contient des accents)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    account_id = data["account_id"]

    # Créer ou mettre à jour le compte. "upsert=True" = mettre à jour s'il existe, sinon le créer.
    # $set ne modifie que le champ "name".
    await db.accounts.update_one({"_id": account_id},
                                 {"$set": {"name": data["account_name"]}}, upsert=True)

    added = 0
    # .get("calls", []) : liste vide si le fichier n'a pas de clé "calls" (pas d'erreur)
    for call in data.get("calls", []):
        # ingest_interaction renvoie True/False ; en Python True vaut 1 et False vaut 0,
        # donc "added += ..." compte les interactions réellement ajoutées.
        added += await ingest_interaction(db, account_id, "call", call["date"], call["call_name"],
                                          call["transcript"], call.get("summary"))
    for email in data.get("emails", []):
        added += await ingest_interaction(db, account_id, "email", email["date"],
                                          email["subject"], email["content"])
    return added


async def main(location):
    """Point d'entrée en ligne de commande. `location` est un dossier de fichiers, ou un seul fichier."""
    location = Path(location)
    # Un fichier -> une liste d'un fichier ; un dossier -> tous ses .json, triés par nom.
    paths = [location] if location.is_file() else sorted(location.glob("*.json"))

    db = database.get_db()
    # Créer les index d'abord (sans effet s'ils existent) : l'index unique content_hash doit
    # exister AVANT d'insérer, et les recherches ont besoin de l'index texte.
    await database.create_indexes(db)

    for path in paths:
        added = await ingest_file(db, path)
        print(f"{path.name}: {added} nouvelles interactions")


# Ce bloc ne s'exécute que si on lance le fichier directement (python -m ingestion.ingest ...),
# pas quand un autre fichier (ou un test) fait "from ingestion.ingest import ...".
if __name__ == "__main__":
    # sys.argv = les arguments de la ligne de commande ; sys.argv[1] = le chemin donné.
    # Sans argument, on charge tout le dossier data/accounts.
    # asyncio.run() lance la fonction asynchrone main() et attend qu'elle se termine.
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "data/accounts"))
