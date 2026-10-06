"""Découpage en chunks et chargement des fichiers (ingestion/)."""

from pathlib import Path

from ingestion.chunking import chunk_text
from ingestion.ingest import ingest_file

DATA = Path(__file__).parent.parent / "data" / "accounts"


def test_un_texte_court_donne_un_seul_chunk():
    assert chunk_text("A short email.") == ["A short email."]


def test_un_long_texte_est_decoupe_avec_chevauchement():
    words = [f"word{i}" for i in range(1000)]
    chunks = chunk_text(" ".join(words), size=500, overlap=100)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    for current, following in zip(chunks, chunks[1:]):
        assert current[-50:].split()[-1] in following  # la fin d'un chunk commence le suivant
    assert set(" ".join(chunks).split()) >= set(words)  # rien n'est perdu


async def test_l_ingestion_cree_les_interactions_et_les_chunks(mongo_db):
    added = await ingest_file(mongo_db, DATA / "account_1.json")

    assert added == 7  # 2 appels + 5 emails dans ce fichier
    assert await mongo_db.interactions.count_documents({"account_id": 1}) == 7
    assert await mongo_db.chunks.count_documents({"account_id": 1}) > 7  # les longs appels en donnent plusieurs
    assert (await mongo_db.accounts.find_one({"_id": 1}))["name"] == "Clinique Saint-Aubin"


async def test_ingerer_deux_fois_n_ajoute_rien(mongo_db):
    await ingest_file(mongo_db, DATA / "account_1.json")
    chunks = await mongo_db.chunks.count_documents({})

    assert await ingest_file(mongo_db, DATA / "account_1.json") == 0
    assert await mongo_db.chunks.count_documents({}) == chunks


async def test_chaque_chunk_pointe_vers_sa_source(mongo_db):
    await ingest_file(mongo_db, DATA / "account_1.json")

    async for chunk in mongo_db.chunks.find():
        source = await mongo_db.interactions.find_one({"_id": chunk["interaction_id"]})
        assert source["account_id"] == chunk["account_id"]
        assert (source["kind"], source["date"], source["title"]) == \
            (chunk["kind"], chunk["date"], chunk["title"])
        assert len(chunk["embedding"]) > 0


async def test_le_resume_d_un_appel_est_son_propre_chunk(mongo_db):
    await ingest_file(mongo_db, DATA / "account_1.json")

    call = await mongo_db.interactions.find_one({"kind": "call"})
    first = await mongo_db.chunks.find_one({"interaction_id": call["_id"], "position": 0})
    assert first["text"] == f"Summary: {call['summary']}"
