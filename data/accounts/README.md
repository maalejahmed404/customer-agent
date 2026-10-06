# Jeu de données

Dix comptes clients synthétiques, en français, utilisés pour l'ingestion et la
démonstration. Aucune donnée réelle : entreprises, personnes et échanges sont fictifs.

Chaque compte suit un cycle de vente complet (prospection, découverte, démonstration,
négociation, signature, puis vie du compte), avec des dates chronologiques et des emails
intercalés entre les appels.

| # | Client | Éditeur | Appels | Emails |
|---|--------|---------|--------|--------|
| 1 | Clinique Saint-Aubin | Medixia Santé | 2 | 5 |
| 2 | Domaines Bertrand-Marçais | Vinalytics | 10 | 25 |
| 3 | Énergie Coopérative du Ponant | Solaria Data SAS | 15 | 20 |
| 4 | Mutuelle Horizon Solidaire | Assurio Technologies | 20 | 15 |
| 5 | Aciéries de Moselle-Est | Thermalys Industrie | 24 | 41 |
| 6 | Éditions Lumière & Cie | Bibliovia Solutions | 24 | 58 |
| 7 | Réseau Pharmacies Amaranthe | Pharmavista Analytics | 15 | 25 |
| 8 | Banque Régionale du Léman | Fiducia Analytics | 43 | 86 |
| 9 | Groupe Hôtelier Castellane | Hospitalys France SAS | 59 | 122 |
| 10 | Textiles Roussel-Pradel | Filoptim Systèmes | 31 | 39 |

## Format

Un fichier `account_N.json` par compte :

```
{
  "tenant_name":  "<éditeur>",
  "account_name": "<client>",
  "account_id":   N,
  "calls":  [ { "date", "call_name", "transcript", "summary", "crm_fields" } ],
  "emails": [ { "date", "subject", "content" } ]
}
```
