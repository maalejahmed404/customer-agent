# Jeu de données comptes — version française régénérée

Ce dossier contient une version entièrement **réécrite et anonymisée** du jeu de
données d'origine. Il conserve **exactement la même structure de fichiers**, mais
son contenu (entreprises, secteurs, personnes, systèmes, sujets, chiffres) est
**intégralement nouveau** : il ne peut plus être rattaché à l'entreprise d'origine.

## Ce qui a été fait

1. **Tout est en français.** Les transcriptions d'appels, les résumés, les objets
   et corps de courriels, ainsi que les champs CRM sont rédigés en français
   naturel (le jeu d'origine mélangeait anglais, français, allemand et espagnol).

2. **Les sujets et les secteurs ont été changés.** On quitte entièrement le
   domaine logistique / supply chain de l'origine pour dix verticales distinctes,
   chacune avec ses douleurs métier, ses systèmes existants et sa réglementation :

   | # | Client | Secteur | Éditeur (fournisseur) |
   |---|--------|---------|------------------------|
   | 1 | Clinique Saint-Aubin | santé — bloc opératoire | Medixia Santé |
   | 2 | Domaines Bertrand-Marçais | viticulture — traçabilité | Vinalytics |
   | 3 | Énergie Coopérative du Ponant | éolien — prévision de production | Solaria Data |
   | 4 | Mutuelle Horizon Solidaire | assurance santé | Assurio |
   | 5 | Aciéries de Moselle-Est | sidérurgie — énergie | Thermalys |
   | 6 | Éditions Lumière & Cie | édition — tirages et droits | Bibliovia |
   | 7 | Réseau Pharmacies Amaranthe | pharmacie — stocks et ruptures | Pharmavista |
   | 8 | Banque Régionale du Léman | banque — conformité | Fiducia |
   | 9 | Groupe Hôtelier Castellane | hôtellerie — revenue management | Hospitalys |
   | 10 | Textiles Roussel-Pradel | textile — ordonnancement qualité | Filoptim |

3. **Rien n'est identique à l'original.** Aucun nom d'entreprise, de personne, de
   produit ou de système de l'origine ne subsiste. Les scénarios de vente ont été
   réécrits de bout en bout.

## Structure conservée (identique à l'origine)

Chaque fichier `account_N.json` :

```
{
  "tenant_name":  "<éditeur>",
  "account_name": "<client>",
  "account_id":   N,
  "calls":  [ { "date", "call_name", "transcript", "summary", "crm_fields" }, ... ],
  "emails": [ { "date", "subject", "content" }, ... ]
}
```

Le nombre d'appels et de courriels par compte est **rigoureusement identique** à
celui de l'origine (de 2 appels / 5 courriels pour le compte 1, jusqu'à 59 appels
/ 122 courriels pour le compte 9).

## Réalisme

Chaque compte suit un cycle de vente complet et crédible : barrage secrétariat,
prospection, découverte, démonstration, atelier technique, revue de sécurité,
proposition, négociation, juridique, comité, signature, puis vie du compte
(lancement, formation, incidents support, points d'avancement, revues
trimestrielles, extension, renouvellement). Les indicateurs progressent dans le
bon sens au fil du temps, les dates sont chronologiques, les champs CRM reflètent
l'étape de l'appel, et les courriels s'intercalent entre les appels.

## Vérifications passées

- **Schéma identique** à l'origine (clés racine, clés d'appel, clés de courriel).
- **Volumétrie identique** (appels et courriels par compte).
- **Aucune fuite** de l'original : contrôle négatif sur les noms de clients,
  d'éditeurs, de personnes et de systèmes de l'origine — aucun ne réapparaît.
- **Zéro doublon** de transcription ou de courriel.
- **Dates croissantes** dans chaque compte.
- **JSON valide, encodage UTF-8**, aucun caractère parasite.
- **Français vérifié** : aucune faute d'élision (`le écart`, `du établissement`,
  `de des`…), articles accordés en genre, prénoms correctement extraits des
  civilités.

## Regénérer

Le jeu est produit de façon **déterministe** (graine fixe) par les scripts du
dossier `generator/` :

```bash
cd generator
python3 build.py ../data       # réécrit les 10 fichiers à l'identique
```

Pour faire varier le contenu, modifier la graine `SEED` dans `build.py`, ou
enrichir les blocs de dialogue dans `beats.py` et les définitions de comptes
dans `sectors.py`.
