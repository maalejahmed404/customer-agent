# Architecture et décisions techniques

Ce document décrit l'architecture de Customer Agent et les décisions qui la structurent.
Pour chaque décision, j'indique ce que j'ai retenu, pourquoi, quelles alternatives j'ai
écartées et ce que le choix coûte.

## 1. Contexte

Une équipe commerciale interroge en langage naturel l'historique d'un compte client :
transcriptions d'appels et emails. Le système doit aussi pouvoir rédiger un email de suivi.

**Exigences**

| # | Exigence | Conséquence sur la conception |
|---|----------|-------------------------------|
| E1 | Isolation stricte entre comptes | le compte est dérivé du jeton, à chaque couche (§4) |
| E2 | Réponses vérifiables | chaque passage garde le lien vers son appel ou email ; la réponse cite ses sources |
| E3 | Aucune action sans validation humaine | l'agent propose, un humain approuve (§3.8) |
| E4 | Latence et coût prévisibles | nombre d'appels LLM fixe, recherches en parallèle (§3.1) |
| E5 | Outils de recherche réutilisables hors de cet agent | serveur MCP indépendant (§3.5) |
| E6 | Coût nul au repos | services sans état, mise à l'échelle à zéro ([DEPLOIEMENT.md](DEPLOIEMENT.md)) |

**Hors périmètre** : ingestion en continu depuis Outlook/Teams, authentification
d'entreprise (SSO), évaluation de la qualité des réponses sur un jeu de référence. Ces
points sont repris en §6.

## 2. Vue d'ensemble

```
Navigateur ─► ui (Streamlit) ─► api (FastAPI + agent LangGraph) ─► mcp (FastMCP) ─► MongoDB
                                    │                │                  │
                                    │                └─► LLM            └─► Voyage AI
                                    └─► MongoDB (utilisateurs, actions, conversations)

ingestion (job) ─► Voyage AI ─► MongoDB
```

| Composant | Rôle | État |
|-----------|------|------|
| `ui/` | interface de chat, affichage des sources, validation des emails | aucun |
| `api/` | authentification, endpoint de chat, actions ; héberge l'agent | aucun |
| `agent/` | graphe LangGraph `planner → retriever → responder → email_drafter` | conversation, via le checkpointer |
| `mcp_server/` | quatre outils de recherche en lecture seule | aucun |
| `ingestion/` | découpage, embeddings, écriture idempotente | — |
| `shared/` | configuration, accès MongoDB, recherche, sécurité, garde-fous | — |

Tout l'état persistant est dans MongoDB. Les services sont sans état et peuvent être
répliqués ou arrêtés librement.

### Trajet d'une question

1. `ui` envoie `POST /chat` avec le jeton JWT.
2. `api` vérifie le jeton et en extrait `account_id` et l'email de l'utilisateur.
3. `planner` : un appel LLM produit un plan structuré (recherches à lancer, filtres de type
   et de dates). Une salutation produit un plan vide et court-circuite la recherche.
4. `retriever` : les recherches du plan partent en parallèle vers le serveur MCP, avec un
   jeton du même compte. Les résultats sont fusionnés par rang et tronqués au budget de
   contexte.
5. `responder` : un appel LLM rédige la réponse à partir des sources numérotées.
6. `email_drafter` (si demandé) : le brouillon est enregistré en `pending`.

## 3. Décisions

### 3.1 Planifier puis exécuter, plutôt qu'une boucle ReAct

**Décision.** L'agent fait exactement deux appels LLM par question (plan, réponse), trois
si un email est demandé. Les recherches du plan s'exécutent en parallèle.

**Raisons.** Dans une boucle ReAct, le nombre d'appels dépend de ce que le modèle décide à
chaque tour : la latence et le coût ne sont pas bornés. Ici ils le sont (E4), et chaque
nœud est une fonction pure de l'état, testable isolément avec un faux LLM.

**Compromis.** L'agent ne peut pas relancer une recherche au vu de ses premiers résultats.
J'ai jugé ce coût acceptable parce que le périmètre est un seul compte et quelques
centaines de passages : un plan correct suffit. Si le planner échoue ou renvoie une sortie
invalide, le retriever cherche avec la question brute, de sorte que l'utilisateur obtient
toujours une réponse.

### 3.2 LangGraph pour l'orchestration

**Décision.** Le pipeline est un graphe LangGraph avec un checkpointer MongoDB.

**Raisons.** Quatre nœuds pourraient s'écrire en fonctions simples. Ce que LangGraph
apporte ici, c'est la persistance de la conversation entre deux requêtes HTTP sans code
dédié, et des arêtes conditionnelles explicites (pas de recherche pour une salutation, pas
de brouillon sans demande d'email).

**Détails.** L'identifiant de fil est construit côté serveur :
`account_id:email:conversation_id`. Un client ne peut donc pas reprendre la conversation
d'un autre utilisateur en devinant un identifiant. Seuls les échanges question/réponse sont
conservés, pas les sources, et un TTL de 30 jours les supprime.

### 3.3 Sorties structurées

**Décision.** Le plan et le brouillon d'email sont des modèles Pydantic (`Plan`,
`EmailDraft`) obtenus par sortie structurée, pas du texte libre analysé après coup.

**Raisons.** La validation est faite par le schéma, et un échec est un cas explicite avec
un repli défini, plutôt qu'une expression régulière qui casse silencieusement.

### 3.4 Recherche hybride, fusion par rang

**Décision.** Chaque question interroge l'index texte français de MongoDB et un index
sémantique (embeddings Voyage, 256 dimensions). Les listes sont fusionnées par Reciprocal
Rank Fusion (k = 60).

**Raisons.** Les deux méthodes échouent sur des cas complémentaires. La recherche lexicale
retrouve un identifiant exact (`FAC-2291`, un montant, un nom de produit) mais ignore les
reformulations. La recherche sémantique rapproche « problème de facturation » de « la
facture est contestée » mais peut manquer une référence précise. Les scores des deux
moteurs n'étant pas sur la même échelle, je fusionne sur le rang : pas de pondération à
calibrer.

**Découpage.** Passages d'environ 1 200 caractères avec 200 de recouvrement ; le résumé
d'un appel forme son propre passage. Chaque passage référence son interaction d'origine,
ce qui rend la citation possible (E2).

**Pas d'index vectoriel.** La similarité cosinus est calculée en mémoire avec numpy sur les
passages du compte. À cette échelle (quelques centaines de passages par compte), le calcul
est exact et l'index n'apporterait que de la configuration. La limite est connue : au-delà
de quelques dizaines de milliers de passages par compte, il faut passer à Atlas Vector
Search. Le changement est confiné à `shared/search.py::semantic_search`.

**Budget de contexte.** Les sources transmises au LLM sont plafonnées à 12 000 caractères,
ce qui borne le coût par requête et évite tout dépassement de fenêtre de contexte.

### 3.5 MCP comme frontière des outils

**Décision.** Les outils de recherche sont exposés par un serveur MCP (FastMCP, transport
Streamable HTTP) dans son propre processus, et l'agent les consomme comme n'importe quel
client.

**Raisons.** Pour ce seul agent, des appels de fonctions suffiraient. Le protocole rend les
mêmes outils utilisables par d'autres clients sans écrire d'API spécifique (E5) ;
`examples/mcp_client_example.py` le démontre avec un client distinct. La séparation impose
aussi une discipline utile : le serveur MCP vérifie lui-même le jeton et n'accepte aucun
argument `account_id`, il ne fait donc pas confiance à l'agent.

**Compromis.** Un saut réseau et un service de plus à déployer.

### 3.6 MongoDB comme unique base

**Décision.** Une seule base pour les interactions, les passages, les utilisateurs, les
actions et les conversations. Appels et emails partagent une collection, distingués par un
champ `kind`.

**Raisons.** Les deux types de documents n'ont pas la même forme, et la requête la plus
fréquente (« tout sur ce compte, sur cette période ») reste une requête unique. MongoDB
fournit l'index texte avec racinisation française et un checkpointer LangGraph officiel,
ce qui évite un second système de stockage.

**Alternative.** PostgreSQL avec pgvector aurait convenu. J'ai privilégié le schéma souple
et le checkpointer existant.

**Idempotence.** Un index unique sur `content_hash` rend l'ingestion rejouable sans
doublon.

### 3.7 Modèles hébergés derrière une interface standard

**Décision.** Le LLM est appelé via une API compatible OpenAI (Gemma 4 31B sur Lightning
AI par défaut, température 0). Les embeddings viennent de Voyage AI, avec des types
d'entrée distincts pour les documents et les requêtes.

**Raisons.** Changer de fournisseur se réduit à trois variables d'environnement
(`LLM_BASE_URL`, `LLM_API_KEY`, `CHAT_MODEL`). Des modèles facturés à la requête sont
cohérents avec E6 : un GPU dédié coûterait en continu, même sans trafic.

**Compromis.** Dépendance à deux fournisseurs externes et à leurs limites de débit. Celle
de Voyage (3 requêtes par minute sans moyen de paiement) rend l'ingestion complète très
lente sur un compte gratuit.

### 3.8 Validation humaine des actions

**Décision.** L'agent ne dispose que d'une opération d'écriture : créer une action au
statut `pending`. L'envoi exige un appel explicite d'un utilisateur authentifié du même
compte.

**Détails.** La transition `pending → approved` est un `find_one_and_update` conditionné
par le statut : deux approbations concurrentes ne produisent qu'un envoi. Sans SMTP
configuré, l'email est écrit dans une collection `outbox`, ce qui permet de démontrer le
parcours complet sans rien émettre.

### 3.9 Asynchrone de bout en bout

**Décision.** Les accès MongoDB, Voyage et MCP sont asynchrones.

**Raisons.** Le temps de réponse est dominé par les entrées-sorties. Les recherches d'un
plan attendent ensemble plutôt qu'à la suite ; un test vérifie ce parallélisme.

### 3.10 Organisation du code

Un dossier par unité déployable (`ui/`, `api/`, `mcp_server/`, `ingestion/`) et un noyau
commun `shared/`. Les modules sont importés par leur nom (`from shared import database`)
et non par leurs fonctions, ce qui permet de les substituer dans les tests.

## 4. Modèle de sécurité

| Menace | Mesure | Vérification |
|--------|--------|--------------|
| Lecture des données d'un autre compte | `account_id` provient uniquement du JWT vérifié ; toute requête MongoDB est filtrée dessus ; les outils MCP n'ont pas d'argument de compte | tests d'isolation au niveau base, MCP et API |
| Falsification de jeton | HS256 épinglé, champs `sub`, `account_id`, `exp` obligatoires, secret d'au moins 32 caractères exigé, durée de vie de 8 h | `tests/test_security.py` |
| Fuite de la base utilisateurs | PBKDF2-SHA256, 200 000 itérations, sel par utilisateur, comparaison en temps constant | `tests/test_security.py` |
| Injection de prompt via un email ou un appel | contenu placé dans le message utilisateur entre délimiteurs aléatoires, caractères invisibles retirés ; surtout, le modèle n'a que des outils en lecture | `tests/test_guards.py` |
| Envoi d'email non voulu ou en double | validation humaine, transition de statut atomique | `tests/test_actions.py` |
| Reprise de la conversation d'un tiers | identifiant de fil dérivé du jeton | `tests/test_api.py` |

La défense contre l'injection repose d'abord sur l'absence de capacité d'action du modèle.
Les délimiteurs et le nettoyage réduisent le risque, ils ne l'éliminent pas.

## 5. Stratégie de test

49 tests, exécutés en intégration continue à chaque push.

- Le LLM et les embeddings sont remplacés par des doubles déterministes
  (`tests/fakes.py`) : aucune clé nécessaire, résultats reproductibles.
- MongoDB est réel, parce que la recherche lexicale dépend du comportement de son index
  texte. Un simulateur aurait validé autre chose que ce qui tourne en production.
- Le serveur MCP est testé à travers le protocole, avec un vrai client, et non en appelant
  ses fonctions directement.

Ce que ces tests ne couvrent pas : la qualité des réponses d'un vrai modèle (§6).

## 6. Limites et évolutions

| Limite actuelle | Évolution prévue |
|-----------------|------------------|
| Utilisateurs et mots de passe gérés par l'application | Microsoft Entra ID ; deux fonctions seulement lisent les jetons (`get_current_user`, `get_account_id`) |
| Ingestion à partir de fichiers | connecteurs Outlook/Teams appelant la même fonction d'ingestion |
| Qualité des réponses non mesurée | jeu de questions de référence et évaluation automatisée |
| Similarité calculée en mémoire | Atlas Vector Search pour les très gros comptes |
| Réponse renvoyée d'un bloc | streaming des jetons vers l'interface |
| Pas de limitation de débit sur `/login` et `/chat` | limitation par utilisateur côté API |

Les écarts propres au déploiement sont listés dans [DEPLOIEMENT.md](DEPLOIEMENT.md).
