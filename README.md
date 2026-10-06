# Customer Agent

Assistant de questions-réponses sur l'historique d'un compte client (transcriptions d'appels
et emails), destiné à une équipe commerciale.

- Les réponses s'appuient uniquement sur les appels et emails du compte de l'utilisateur.
- Chaque réponse cite ses sources `[1]`, `[2]` ; chaque source ouvre l'appel ou l'email complet.
- La conversation est mémorisée, ce qui permet les questions de relance.
- Un email rédigé par l'assistant n'est envoyé qu'après validation par un humain.

**Stack** : LangGraph · MCP (FastMCP) · FastAPI · MongoDB · Streamlit · Azure Container Apps
**Modèles** : Gemma 4 31B sur Lightning AI (chat) · Voyage AI `voyage-4-large` (embeddings)

**Documentation** : [architecture et décisions techniques](docs/ARCHITECTURE.md) ·
[conception du déploiement Azure](docs/DEPLOIEMENT.md)

## Architecture

```
  Navigateur
      │
      ▼
  ┌───────────┐ /login, /chat ┌───────────────────┐ outils MCP  ┌────────────┐
  │    ui     │ ────────────► │        api        │ ──────────► │ mcp_server │
  │ Streamlit │ /actions ...  │ FastAPI           │ + jeton JWT │ FastMCP    │
  └───────────┘               │ + agent LangGraph │             └─────┬──────┘
                              └──┬─────────────┬──┘                   │
                                 │             │                      │
                                 ▼             ▼                      │
                          LLM (Lightning)   MongoDB ◄─────────────────┘
                                               ▲
                                               │
                                           ingestion

  Voyage AI (embeddings) est appelé par mcp_server (requêtes) et ingestion (documents).
```

Une seule image Docker, lancée avec une commande différente par service :

| Service   | Code              | Commande                                   | Port |
|-----------|-------------------|--------------------------------------------|------|
| ui        | `ui/`             | `streamlit run ui/streamlit_app.py`        | 8501 |
| api       | `api/`, `agent/`  | `uvicorn api.main:app --port 8000`         | 8000 |
| mcp       | `mcp_server/`     | `python -m mcp_server.server`              | 8001 |
| ingestion | `ingestion/`      | `python -m ingestion.ingest data/accounts` | —    |

L'agent LangGraph est une bibliothèque appelée par `POST /chat` : il s'exécute dans le
conteneur `api`.

### Traitement d'une question

![Graphe LangGraph](docs/agent_graph.png)

1. `ui` envoie `POST /chat` avec la question et le jeton JWT.
2. `api` vérifie le jeton et en extrait l'`account_id`.
3. `planner` : le LLM produit un plan de recherche structuré (requêtes, filtres). Une
   salutation ne déclenche aucune recherche.
4. `retriever` : les recherches du plan partent en parallèle vers le serveur MCP, avec un
   jeton du même compte. Les résultats sont fusionnés par Reciprocal Rank Fusion puis
   tronqués à 12 000 caractères.
5. `responder` : le LLM répond à partir des sources numérotées et les cite.
6. `email_drafter`, si un email est demandé : le brouillon est enregistré comme action
   `pending`, à approuver ou refuser dans l'interface.

### Invariants

- L'`account_id` provient du jeton JWT, jamais du corps d'une requête ni d'un argument
  d'outil. Toute requête MongoDB est filtrée dessus.
- L'agent ne peut que proposer un email. L'envoi exige l'approbation d'un utilisateur du
  même compte, via l'API.
- Le contenu des appels et emails est traité comme une donnée, pas comme une instruction :
  il est placé dans le message utilisateur, entre délimiteurs aléatoires
  (`shared/guards.py`).

## Organisation du code

```
shared/            configuration, accès MongoDB, recherche, sécurité, garde-fous
ingestion/         découpage, embeddings, écriture idempotente des interactions
mcp_server/        quatre outils de recherche en lecture seule, compte lu dans le jeton
agent/             graphe LangGraph : state, prompts, client MCP, nœuds
  nodes/           planner, retriever, responder, email_drafter
actions/           cycle pending → approved → sent / rejected, envoi SMTP ou outbox
api/               FastAPI : login, chat, interactions, actions
ui/                interface Streamlit
scripts/           création d'utilisateur en ligne de commande
examples/          client MCP indépendant utilisant les mêmes outils
infra/             Bicep : Azure Container Apps
data/accounts/     jeu de données synthétique en français (10 comptes)
tests/             49 tests pytest
```

## Lancer en local

Les commandes s'exécutent depuis la racine du dépôt. Trois variables sont à renseigner
dans `.env` : `JWT_SECRET`, `LLM_API_KEY`, `VOYAGE_API_KEY`.

### Avec Docker

```powershell
copy .env.example .env
docker compose up --build -d
docker compose run --rm api python -m ingestion.ingest data/accounts/account_1.json
docker compose run --rm api python -m scripts.create_user camille@vendor.fr mon-mot-de-passe 1
```

L'interface est sur http://localhost:8501, la documentation de l'API sur
http://localhost:8000/docs. L'utilisateur créé appartient au compte 1 ; le jeu de données
contient les comptes 1 à 10.

### Sans Docker

MongoDB 7+ est requis (`docker compose up -d mongo` suffit).

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env

python -m ingestion.ingest data/accounts/account_1.json
python -m scripts.create_user camille@vendor.fr mon-mot-de-passe 1

python -m mcp_server.server             # port 8001
uvicorn api.main:app --port 8000        # port 8000
streamlit run ui/streamlit_app.py       # port 8501
```

Sans moyen de paiement, un compte Voyage AI est limité à 3 requêtes par minute :
l'ingestion des dix comptes devient très longue. Un seul compte suffit pour essayer.

### Utiliser les outils depuis un autre client MCP

Le serveur MCP est indépendant de l'agent. Tout client MCP peut l'interroger en
Streamable HTTP sur `http://localhost:8001/mcp` avec l'en-tête
`Authorization: Bearer <jeton>` obtenu par `POST /login`, et ne voit que le compte du jeton.

```powershell
python examples/mcp_client_example.py camille@vendor.fr mon-mot-de-passe "Hôpital Manager"
```

## Tests

```powershell
docker compose up -d mongo
pytest -q
```

49 tests, sans clé d'API : le LLM et les embeddings sont remplacés par des doubles
déterministes (`tests/fakes.py`). MongoDB est réel, car la recherche lexicale dépend de son
index texte ; sans MongoDB, les tests concernés sont ignorés. L'intégration continue les
exécute à chaque push.

| Fichier              | Ce qui est vérifié                                                    |
|----------------------|-----------------------------------------------------------------------|
| `test_security.py`   | mots de passe, jetons expirés ou signés avec un autre secret          |
| `test_guards.py`     | injection de prompt, caractères invisibles, adresses email            |
| `test_ingestion.py`  | découpage, idempotence, lien de chaque passage vers sa source         |
| `test_search.py`     | recherche lexicale et sémantique, filtres, isolation entre comptes    |
| `test_mcp_server.py` | serveur réel : jeton obligatoire, compte lu dans le jeton, parallélisme |
| `test_agent.py`      | plan, fusion, citations, pannes, mémoire de conversation              |
| `test_actions.py`    | aucun envoi sans validation humaine, un seul envoi par action         |
| `test_api.py`        | login, compte dérivé du jeton, conversations séparées par utilisateur |

## Déploiement

L'infrastructure Azure est décrite dans `infra/main.bicep` : trois Container Apps (`ui`
publique, `api` et `mcp` internes) avec mise à l'échelle à zéro, et un job d'ingestion.
Les décisions et la procédure sont dans [docs/DEPLOIEMENT.md](docs/DEPLOIEMENT.md).
