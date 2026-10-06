"""Les requêtes de recherche dans MongoDB (shared/search.py)."""

from shared import search
from tests.fakes import fake_vector


async def test_la_recherche_par_mots_cles_trouve_les_mots_exacts(sample_data):
    results = await search.keyword_search(sample_data, 1, "facture")

    assert results[0]["title"] == "Contestation de facture"
    assert results[0]["interaction_id"]  # chaque résultat pointe vers son appel ou email


async def test_la_recherche_par_mots_cles_ne_sort_jamais_du_compte(sample_data):
    assert await search.keyword_search(sample_data, 1, "Zéphyr budget") == []
    results = await search.keyword_search(sample_data, 2, "facture")
    assert results and {r["title"] for r in results} <= {"Budget confidentiel", "Lancement"}


async def test_la_recherche_par_mots_cles_filtre_par_type_et_par_date(sample_data):
    calls = await search.keyword_search(sample_data, 1, "Hélène", kind="call")
    assert [r["title"] for r in calls] == ["Appel de découverte"]

    recent = await search.keyword_search(sample_data, 1, "Hélène", date_from="2025-03-01")
    assert [r["date"] for r in recent] == ["2025-03-10"]


async def test_la_recherche_par_le_sens_classe_le_texte_le_plus_proche_en_premier(sample_data):
    query = fake_vector("les journées de formation facturées deux fois")
    results = await search.semantic_search(sample_data, 1, query, limit=3)

    assert results[0]["title"] == "Contestation de facture"
    assert results[0]["score"] >= results[-1]["score"]


async def test_la_recherche_par_le_sens_ne_sort_jamais_du_compte(sample_data):
    results = await search.semantic_search(sample_data, 1, fake_vector("budget projet Zéphyr"),
                                           limit=10)

    own_ids = {str(doc["_id"]) async for doc in sample_data.interactions.find({"account_id": 1})}
    assert results and {r["interaction_id"] for r in results} <= own_ids


async def test_les_dernieres_interactions_arrivent_de_la_plus_recente_a_la_plus_ancienne(sample_data):
    results = await search.list_interactions(sample_data, 1)

    assert [r["date"] for r in results] == ["2025-03-10", "2025-02-03", "2025-01-13"]
    # la source complète du compte 1 ne peut pas être ouverte depuis le compte 2
    assert await search.get_interaction(sample_data, 1, results[0]["interaction_id"])
    assert await search.get_interaction(sample_data, 2, results[0]["interaction_id"]) is None
