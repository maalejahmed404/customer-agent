"""Configuration commune des tests.

- Les tests utilisent un VRAI MongoDB (la recherche par mots-clés a besoin de l'index texte).
  En lancer un : docker compose up -d mongo   (ou MONGO_URI=... vers un autre serveur)
  Sans MongoDB, les tests qui en ont besoin sont simplement ignorés ("skipped").
- Aucune clé API n'est nécessaire : le LLM et les embeddings sont remplacés par des faux
  (voir fakes.py).
"""

import os
import socket
import threading
import time
import uuid

# Ces variables doivent être définies AVANT d'importer le code (settings est lu à l'import)
os.environ["DB_NAME"] = f"test_customer_agent_{uuid.uuid4().hex[:8]}"
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-long-enough-for-hs256-0123456789")

import pytest  # noqa: E402
import uvicorn  # noqa: E402
from pymongo import AsyncMongoClient, MongoClient  # noqa: E402

from ingestion.ingest import ingest_interaction  # noqa: E402
from shared import database, embeddings  # noqa: E402
from shared.config import settings  # noqa: E402
from tests.fakes import fake_vector  # noqa: E402

# Deux petits comptes : chaque test sur le compte 1 peut vérifier que le compte 2 n'apparaît jamais.
SAMPLE = [
    (1, "call", "2025-01-13", "Appel de découverte",
     "Camille : Comment planifiez-vous les salles aujourd'hui ?\n"
     "Hélène : Avec Hôpital Manager et un fichier Excel. Le taux d'occupation des salles est de 62 %.",
     "Planification des salles dans Hôpital Manager et Excel, occupation à 62 %."),
    (1, "email", "2025-02-03", "Proposition tarifaire",
     "Bonjour Hélène, voici notre proposition : 18 000 euros par an pour le module de planification. "
     "Cordialement, Camille", None),
    (1, "email", "2025-03-10", "Contestation de facture",
     "Bonjour Camille, nous contestons la facture FAC-2291 : les journées de formation ont été "
     "facturées deux fois. Hélène Vasseur (helene.vasseur@clinique-saint-aubin.fr)", None),
    (2, "email", "2025-02-20", "Budget confidentiel",
     "Confidentiel : le budget du projet Zéphyr est de 2 millions d'euros. La facture arrive en avril.",
     None),
    (2, "call", "2025-02-21", "Lancement",
     "Nous avons parlé du déploiement Zéphyr et du calendrier de facturation.", None),
]


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    """Remplace Voyage AI par un faux embedding (aucune clé API nécessaire)."""
    async def embed(texts, input_type="document"):
        return [fake_vector(text) for text in texts]
    monkeypatch.setattr(embeddings, "embed", embed)


@pytest.fixture
async def mongo_db():
    """Une base de test vide, avec ses index."""
    client = AsyncMongoClient(settings.mongo_uri, serverSelectionTimeoutMS=1000)
    try:
        await client.admin.command("ping")
    except Exception:
        await client.close()
        pytest.skip(f"MongoDB not reachable at {settings.mongo_uri} (docker compose up -d mongo)")
    db = client[settings.db_name]
    for name in await db.list_collection_names():
        await db[name].delete_many({})
    await database.create_indexes(db)
    yield db
    await client.close()


@pytest.fixture
def db(mongo_db, monkeypatch):
    """La même base, renvoyée aussi par database.get_db() au code testé."""
    monkeypatch.setattr(database, "get_db", lambda: mongo_db)
    return mongo_db


@pytest.fixture
async def sample_data(mongo_db):
    for account_id, kind, date, title, body, summary in SAMPLE:
        await ingest_interaction(mongo_db, account_id, kind, date, title, body, summary)
    await mongo_db.accounts.insert_many([{"_id": 1, "name": "Clinique Saint-Aubin"},
                                         {"_id": 2, "name": "Zéphyr Industries"}])
    return mongo_db


@pytest.fixture(scope="session")
def mcp_url():
    """Le vrai serveur MCP, lancé dans un thread pendant toute la session de tests."""
    from mcp_server.server import mcp

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(mcp.streamable_http_app(), host="127.0.0.1",
                                           port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def pytest_sessionfinish(session, exitstatus):
    """Supprime la base de test à la fin."""
    try:
        MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=1500).drop_database(settings.db_name)
    except Exception:
        pass
