# Déployer Customer Agent sur Azure

Guide pas à pas. Les commandes sont pour **PowerShell (Windows)** et se lancent depuis le
dossier `customer-agent/`.

**Sommaire**
0. [Le résumé en 30 secondes](#0-le-résumé-en-30-secondes)
1. [Le schéma : ce qui tourne où](#1-le-schéma--ce-qui-tourne-où)
2. [Où va chaque morceau de code](#2-où-va-chaque-morceau-de-code)
3. [Les endpoints (API, MCP, interface)](#3-les-endpoints)
4. [Le trajet d'une question sur Azure](#4-le-trajet-dune-question-sur-azure)
5. [Prérequis](#5-prérequis)
6. [Déploiement pas à pas](#6-déploiement-pas-à-pas)
7. [Variables d'environnement et secrets](#7-variables-denvironnement-et-secrets)
8. [Mettre à jour après un changement de code](#8-mettre-à-jour-après-un-changement-de-code)
9. [Surveiller et déboguer](#9-surveiller-et-déboguer)
10. [Coûts et suppression](#10-coûts-et-suppression)
11. [Pour aller plus loin](#11-pour-aller-plus-loin)

---

## 0. Le résumé en 30 secondes

- On construit **une seule image Docker** et on la pousse dans **Azure Container Registry (ACR)**.
- Le fichier `infra/main.bicep` crée, à partir de cette image, **3 Container Apps** — `ui`, `api`,
  `mcp` — et **1 Job** `ingest`.
- **Seule `ui` est accessible depuis Internet.** `api` et `mcp` sont **internes**.
- **L'agent LangGraph tourne dans le conteneur `api`** (il n'a pas de conteneur à lui).
- **Le serveur MCP a son propre conteneur `mcp`.**
- La base de données est **MongoDB Atlas** (hors Azure), le LLM est sur **Lightning AI**, les
  embeddings chez **Voyage AI**.
- Chaque app descend à **0 réplica** quand personne ne l'utilise : pas de coût de calcul la nuit.

---

## 1. Le schéma : ce qui tourne où

```
                               Internet (navigateur)
                                        │
                                        │  https://ui.<domaine>
                                        ▼
╔═══════════════════ Groupe de ressources "customer-agent" ════════════════════╗
║                                                                              ║
║  ┌───────────── Environnement Container Apps "customer-agent-env" ────────┐  ║
║  │                                                                        │  ║
║  │  ┌─────────────┐        ┌───────────────────┐        ┌──────────────┐  │  ║
║  │  │ ui          │ HTTPS  │ api               │  MCP   │ mcp          │  │  ║
║  │  │ Streamlit   │───────►│ FastAPI           │───────►│ serveur MCP  │  │  ║
║  │  │ PUBLIC      │        │ + agent LangGraph │ + JWT  │ (FastMCP)    │  │  ║
║  │  │ port 8501   │        │ INTERNE, 8000     │        │ INTERNE, 8001│  │  ║
║  │  └─────────────┘        └───────────────────┘        └──────────────┘  │  ║
║  │                                                                        │  ║
║  │  ┌─────────────┐                                                       │  ║
║  │  │ Job ingest  │  lancé à la main, charge data/accounts                │  ║
║  │  └─────────────┘                                                       │  ║
║  └────────────────────────────────────────────────────────────────────────┘  ║
║                                                                              ║
║  Container Registry (ACR) : l'image Docker    Log Analytics : tous les logs  ║
╚══════════════════════════════════════════════════════════════════════════════╝

 Services externes (hors Azure), appelés par :
   MongoDB Atlas  ◄──  api, mcp, ingest   données, utilisateurs, actions, conversations
   Lightning AI   ◄──  api                le LLM (planner, réponse, brouillon d'email)
   Voyage AI      ◄──  mcp, ingest        les embeddings
```

`<domaine>` est le domaine de l'environnement Container Apps, par exemple
`happy-sand-1a2b3c4d.francecentral.azurecontainerapps.io`. Pour le connaître :

```powershell
az containerapp env show -n customer-agent-env -g customer-agent --query properties.defaultDomain -o tsv
```

---

## 2. Où va chaque morceau de code

| Morceau                  | Dossier(s)                     | Ressource Azure            | Nom      | Accès                          | Port | Commande de démarrage                          |
|--------------------------|--------------------------------|----------------------------|----------|--------------------------------|------|------------------------------------------------|
| Interface web            | `ui/`                          | Container App              | `ui`     | **Public** (Internet)          | 8501 | `streamlit run ui/streamlit_app.py ...`        |
| API REST                 | `api/`                         | Container App              | `api`    | Interne                        | 8000 | `uvicorn api.main:app ...`                     |
| **Agent LangGraph**      | `agent/`                       | *dans* le Container App    | `api`    | — (pas de port à lui)          | —    | lancé par `POST /chat`                         |
| Validation des emails    | `actions/`                     | *dans* le Container App    | `api`    | —                              | —    | appelé par l'agent et par `/actions/...`       |
| **Serveur MCP**          | `mcp_server/`                  | Container App              | `mcp`    | Interne (public si `exposeMcp`)| 8001 | `python -m mcp_server.server`                  |
| Chargement des données   | `ingestion/` + `data/`         | Container Apps **Job**     | `ingest` | pas d'accès réseau entrant     | —    | `python -m ingestion.ingest data/accounts`     |
| Code commun              | `shared/`                      | dans les 4 ci-dessus       | —        | —                              | —    | —                                              |
| Base de données          | (`shared/database.py`)         | **MongoDB Atlas** (externe)| —        | Internet, avec mot de passe    | —    | —                                              |
| Infrastructure           | `infra/main.bicep`             | décrit tout ce qui précède | —        | —                              | —    | `az deployment group create ...`               |

Les commandes de démarrage sont écrites dans `infra/main.bicep` (champ `command` de chaque app).

### Pourquoi l'agent LangGraph est-il dans le conteneur `api` ?

- L'agent est une **bibliothèque Python** (`agent/graph.py → build_graph()`), pas un serveur :
  il n'écoute sur aucun port.
- C'est l'endpoint `POST /chat` (`api/routes/chat.py`) qui le lance avec `agent.ainvoke(...)`.
- Résultat : un saut réseau en moins, un conteneur en moins à gérer, et l'agent monte en charge
  en même temps que l'API.
- Si un jour il faut le séparer : ajouter un petit FastAPI dans `agent/` qui expose `/chat`,
  ajouter une 4e Container App dans le Bicep, et faire appeler cette adresse par l'API.
  Les nœuds du graphe ne changent pas.

### Pourquoi le serveur MCP a-t-il son propre conteneur ?

- Pour être **réutilisable** par d'autres clients MCP (Claude Desktop, Copilot Studio, l'agent
  d'une autre équipe) sans passer par notre API.
- Il monte en charge séparément (l'agent lui envoie plusieurs recherches en même temps).
- Il vérifie **lui-même** le token : même exposé sur Internet, un client ne voit que son compte.

### Pourquoi une seule image pour tout ?

- Un seul build, une seule version : `ui`, `api`, `mcp` et `ingest` ont toujours le même code.
- C'est la **commande de démarrage** qui choisit quel service tourne.

---

## 3. Les endpoints

### 3.1 Interface — Container App `ui` (publique)

| URL                     | Ce qu'on y fait                                                            |
|-------------------------|----------------------------------------------------------------------------|
| `https://ui.<domaine>`  | se connecter, poser des questions, voir les sources, approuver les emails  |

L'interface n'appelle que l'API (variable `API_URL = https://api.internal.<domaine>`).

### 3.2 API — Container App `api` (interne)

Adresse : `https://api.internal.<domaine>` — joignable **seulement depuis l'environnement**
(c'est-à-dire par l'app `ui`).
Tous les endpoints sauf `/health`, `/login` et `/docs` demandent le header
`Authorization: Bearer <token>`.

| Méthode | Chemin                        | Token | Corps (JSON)                          | Réponse                                                  | Code                          |
|---------|-------------------------------|-------|---------------------------------------|----------------------------------------------------------|-------------------------------|
| GET     | `/health`                     | non   | —                                     | `{"status": "ok"}`                                       | `api/main.py`                 |
| POST    | `/login`                      | non   | `{"email", "password"}`               | `{"token", "email", "account_id", "account_name"}`       | `api/routes/login.py`         |
| POST    | `/chat`                       | oui   | `{"question", "conversation_id"}`     | `{"answer", "sources": [...], "action_id"}`              | `api/routes/chat.py`          |
| GET     | `/interactions/{id}`          | oui   | —                                     | l'appel ou l'email complet (`title`, `body`, ...)        | `api/routes/interactions.py`  |
| GET     | `/actions?status=pending`     | oui   | —                                     | la liste des actions du compte                           | `api/routes/actions.py`       |
| POST    | `/actions/{id}/approve`       | oui   | —                                     | l'action, `status` = `sent` (ou `failed`)                | `api/routes/actions.py`       |
| POST    | `/actions/{id}/reject`        | oui   | —                                     | l'action, `status` = `rejected`                          | `api/routes/actions.py`       |
| GET     | `/docs`                       | non   | —                                     | la documentation interactive (Swagger)                   | généré par FastAPI            |

Exemple de réponse de `POST /chat` :

```json
{
  "answer": "Le client conteste la facture FAC-2291 [1].",
  "sources": [
    {"number": 1, "interaction_id": "665f...", "kind": "email", "date": "2025-03-10",
     "title": "Contestation de facture", "text": "...", "score": 0.83}
  ],
  "action_id": null
}
```

Codes d'erreur : `400` question vide ou trop longue · `401` token manquant, invalide ou expiré ·
`404` introuvable (ou appartient à un autre compte) · `502` l'agent a échoué (LLM ou MCP).

> **Tester l'API depuis mon PC ?** Elle est interne, donc pas joignable depuis Internet.
> Le plus simple est de la tester en local (README, section 5). Sinon, on peut l'ouvrir
> temporairement :
> `az containerapp ingress update -n api -g customer-agent --type external`
> puis `https://api.<domaine>/docs`, et la refermer juste après avec `--type internal`.
> Pendant ce temps, l'API est exposée sur Internet et l'adresse interne utilisée par l'UI
> peut ne plus répondre : à faire seulement pour un test court.

### 3.3 Serveur MCP — Container App `mcp` (interne par défaut)

| Cas                                  | Adresse                                    |
|--------------------------------------|--------------------------------------------|
| Interne (défaut, utilisée par l'agent via `MCP_URL`) | `https://mcp.internal.<domaine>/mcp` |
| Publique (si `"exposeMcp": true` dans `params.json`) | `https://mcp.<domaine>/mcp`          |
| Santé                                | `GET /health` sur la même adresse, sans `/mcp` |

Transport **Streamable HTTP**, header obligatoire `Authorization: Bearer <token>` (le même token
que celui renvoyé par `/login`).

| Outil               | Arguments                                                                    | Renvoie                      |
|---------------------|------------------------------------------------------------------------------|------------------------------|
| `keyword_search`    | `query`, `kind` (`call`/`email`/`any`), `date_from`, `date_to` (AAAA-MM-JJ), `limit` (max 20) | `{"results": [...]}` |
| `semantic_search`   | mêmes arguments                                                              | `{"results": [...]}`         |
| `list_interactions` | `kind`, `date_from`, `date_to`, `limit`                                      | `{"results": [...]}`         |
| `get_interaction`   | `interaction_id`                                                             | l'appel ou l'email complet   |

Aucun outil n'a d'argument `account_id` : le compte est **lu dans le token** (`get_account_id()`
dans `mcp_server/server.py`).

### 3.4 Job `ingest`

Pas d'adresse : on le lance à la main (`az containerapp job start`, voir étape 8). Il exécute
`python -m ingestion.ingest data/accounts` avec les fichiers inclus dans l'image.

---

## 4. Le trajet d'une question sur Azure

```
 1. [navigateur]  l'utilisateur tape sa question dans https://ui.<domaine>
 2. [ui]          POST https://api.internal.<domaine>/chat   + token JWT
 3. [api]         vérifie le token -> account_id (api/dependencies.py)
 4. [api/agent]   planner   : appel au LLM (Lightning AI) -> plan de recherche
 5. [api/agent]   retriever : N appels d'outils EN PARALLÈLE vers https://mcp.internal.<domaine>/mcp
 6. [mcp]         vérifie le token, cherche dans MongoDB Atlas (+ Voyage AI pour semantic_search)
 7. [api/agent]   fusionne les résultats, garde les meilleurs (12 000 caractères max)
 8. [api/agent]   responder : appel au LLM -> réponse avec citations [1], [2]
 9. [api/agent]   (si email demandé) email_drafter : brouillon -> MongoDB, statut "pending"
10. [api]         sauvegarde la conversation dans MongoDB (checkpointer LangGraph)
11. [ui]          affiche la réponse, les sources, et l'email en attente
12. [ui -> api]   "Approuver et envoyer" -> POST /actions/{id}/approve -> envoi SMTP (ou "outbox")
```

---

## 5. Prérequis

| Quoi                        | Pour quoi faire                                         | Où / comment                                        |
|-----------------------------|---------------------------------------------------------|-----------------------------------------------------|
| Abonnement Azure            | héberger les conteneurs                                 | portal.azure.com                                    |
| Azure CLI (`az`)            | lancer les commandes de ce guide                        | `az --version` pour vérifier                        |
| Python 3.12 + venv          | charger les données et créer l'utilisateur depuis le PC | README, section 5                                   |
| Cluster **MongoDB Atlas**   | la base de données (le niveau gratuit M0 suffit)        | cloud.mongodb.com                                   |
| Clé **Lightning AI**        | le LLM                                                  | lightning.ai                                        |
| Clé **Voyage AI**           | les embeddings                                          | voyageai.com                                        |
| Docker Desktop (optionnel)  | seulement si `az acr build` est refusé (étape 4)        | docker.com                                          |

---

## 6. Déploiement pas à pas

Deux variables utilisées dans toutes les commandes :

```powershell
$RG  = "customer-agent"      # le groupe de ressources (le "dossier" Azure qui contient tout)
$LOC = "francecentral"       # la région (Paris)
```

### Étape 1 — Préparer MongoDB Atlas

1. Créer un cluster gratuit **M0**, dans une région proche (ex. Paris).
2. **Database Access** : créer un utilisateur et un mot de passe.
3. **Network Access** : ajouter `0.0.0.0/0`. Container Apps n'a pas d'adresse IP de sortie fixe,
   la protection repose donc sur le mot de passe.
4. **Connect → Drivers** : copier l'adresse `mongodb+srv://...` (c'est le `MONGO_URI`).

### Étape 2 — Charger les données et créer un utilisateur (depuis votre PC)

```powershell
.venv\Scripts\activate
$env:MONGO_URI = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority"

python -m ingestion.ingest data/accounts/account_1.json          # besoin de VOYAGE_API_KEY dans .env
python -m scripts.create_user camille@vendor.fr "<mot de passe solide>" 1

Remove-Item Env:MONGO_URI      # pour revenir au MongoDB local ensuite
```

`$env:MONGO_URI` est prioritaire sur le fichier `.env` : les données partent bien dans Atlas.
(Pour charger tous les comptes, on peut aussi utiliser le Job `ingest` à l'étape 8.)

### Étape 3 — Préparer Azure (une seule fois par abonnement)

```powershell
az login
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.ContainerRegistry
az extension add --name containerapp
az group create -n $RG -l $LOC
```

### Étape 4 — Créer le registre d'images et construire l'image

```powershell
$ACR = "customeragent$(Get-Random -Maximum 99999)"   # nom unique : minuscules et chiffres
az acr create -g $RG -n $ACR --sku Basic --admin-enabled true
az acr build -r $ACR -t customer-agent:1 .          # construit l'image DANS Azure (pas besoin de Docker)
echo $ACR                                            # notez ce nom, il sert pour les mises à jour
az acr credential show -n $ACR --query "passwords[0].value" -o tsv   # mot de passe du registre
```

Si `az acr build` est refusé (fréquent sur les abonnements étudiants), construisez en local avec
Docker Desktop :

```powershell
az acr login -n $ACR
docker build -t "$ACR.azurecr.io/customer-agent:1" .
docker push "$ACR.azurecr.io/customer-agent:1"
```

### Étape 5 — Remplir les paramètres

```powershell
copy infra\params.example.json infra\params.json
python -c "import secrets; print(secrets.token_urlsafe(48))"     # -> jwtSecret
```

| Paramètre          | Valeur                                                                 |
|--------------------|------------------------------------------------------------------------|
| `image`            | `<ACR>.azurecr.io/customer-agent:1`                                    |
| `registryServer`   | `<ACR>.azurecr.io`                                                     |
| `registryUsername` | `<ACR>`                                                                |
| `registryPassword` | le résultat de `az acr credential show` (étape 4)                      |
| `mongoUri`         | l'adresse Atlas (étape 1)                                              |
| `jwtSecret`        | la chaîne générée ci-dessus (au moins 32 caractères)                   |
| `llmApiKey`        | la clé Lightning AI                                                    |
| `voyageApiKey`     | la clé Voyage AI                                                       |
| `exposeMcp`        | `false` (mettre `true` pour ouvrir le serveur MCP à d'autres clients)  |

> `infra/params.json` contient des secrets : il est dans `.gitignore`, **ne le commitez jamais**.

### Étape 6 — Déployer

```powershell
az deployment group create -g $RG -f infra/main.bicep -p "@infra/params.json"
```

Quelques minutes. Cela crée : l'espace de logs, l'environnement, les apps `mcp`, `api`, `ui`
et le Job `ingest`.

### Étape 7 — Récupérer les adresses

```powershell
az deployment group show -g $RG -n main --query properties.outputs -o json
```

- `url` : l'adresse publique de l'interface (`https://ui.<domaine>`)
- `apiUrl` : l'adresse interne de l'API
- `mcpUrl` : l'adresse du serveur MCP (interne, ou publique si `exposeMcp`)

### Étape 8 — (Optionnel) Charger tous les comptes avec le Job

```powershell
az containerapp job start -g $RG -n ingest
az containerapp job execution list -g $RG -n ingest -o table     # suivre l'exécution
```

Le Job charge tous les fichiers de `data/accounts` inclus dans l'image. Relancer ne crée pas de
doublons. Avec Voyage AI sans moyen de paiement (3 requêtes/minute), c'est très long et le Job
s'arrête au bout d'une heure : relancez-le, il reprendra là où il en était.

### Étape 9 — Tester

1. Ouvrir l'adresse `url` de l'étape 7.
2. Se connecter avec l'utilisateur de l'étape 2.
3. Poser une question, par exemple *« Résume le dernier appel. »*

La première requête après une période calme prend quelques secondes : les conteneurs
redémarrent depuis 0 réplica. C'est normal.

---

## 7. Variables d'environnement et secrets

Toutes sont lues par `shared/config.py`. Dans `main.bicep`, les valeurs sensibles sont des
**secrets** Container Apps (`secretRef`), jamais écrites en clair.

| Variable          | Secret | Utilisée par        | Rôle                                                    |
|-------------------|--------|---------------------|---------------------------------------------------------|
| `MONGO_URI`       | oui    | api, mcp, ingest    | adresse de MongoDB Atlas                                |
| `JWT_SECRET`      | oui    | api, mcp            | l'API signe les tokens, le serveur MCP les vérifie      |
| `LLM_API_KEY`     | oui    | api (agent)         | clé du LLM                                              |
| `LLM_BASE_URL`    | non    | api (agent)         | adresse de l'API compatible OpenAI                      |
| `CHAT_MODEL`      | non    | api (agent)         | nom du modèle                                           |
| `VOYAGE_API_KEY`  | oui    | mcp, ingest         | clé des embeddings                                      |
| `EMBEDDING_MODEL` | non    | mcp, ingest         | modèle d'embeddings                                     |
| `MCP_URL`         | non    | api (agent)         | `https://mcp.internal.<domaine>/mcp`                    |
| `API_URL`         | non    | ui                  | `https://api.internal.<domaine>`                        |
| `SMTP_*`          | oui    | api (actions)       | optionnel : envoi réel des emails (sinon "outbox")      |

Changer de fournisseur de LLM (ex. Azure OpenAI) = changer `LLM_BASE_URL`, `LLM_API_KEY`,
`CHAT_MODEL`. Aucune ligne de code à modifier.

**Activer le vrai envoi d'emails (SMTP)** — rapide, en ligne de commande :

```powershell
az containerapp secret set -n api -g $RG --secrets smtp-password="<mot de passe>"
az containerapp update -n api -g $RG --set-env-vars SMTP_HOST=smtp.office365.com SMTP_PORT=587 SMTP_USER=<utilisateur> SMTP_PASSWORD=secretref:smtp-password SMTP_FROM=<adresse>
```

Attention : un nouveau `az deployment group create` remet les variables décrites dans
`main.bicep`. Pour que ce soit permanent, ajoutez-les aussi dans `main.bicep` (listes `secrets`
et `envVars`).

---

## 8. Mettre à jour après un changement de code

Toujours avec un **nouveau tag** (`:2`, `:3`...) : avec le même tag, Azure ne voit pas de
changement et ne redémarre pas les apps.

**Option A (recommandée) — tout redéployer avec le Bicep :**

```powershell
az acr build -r $ACR -t customer-agent:2 .
# dans infra/params.json : "image": { "value": "<ACR>.azurecr.io/customer-agent:2" }
az deployment group create -g $RG -f infra/main.bicep -p "@infra/params.json"
```

**Option B (rapide) — changer l'image app par app :**

```powershell
$IMG = "$ACR.azurecr.io/customer-agent:2"
az acr build -r $ACR -t customer-agent:2 .
az containerapp update -n api -g $RG --image $IMG
az containerapp update -n mcp -g $RG --image $IMG
az containerapp update -n ui  -g $RG --image $IMG
az containerapp job update -n ingest -g $RG --image $IMG
```

Nouvelle fenêtre PowerShell et `$ACR` perdu ? `az acr list -g $RG --query "[].name" -o tsv`

---

## 9. Surveiller et déboguer

```powershell
az containerapp logs show -n api -g $RG --follow                  # logs de l'API et de l'agent
az containerapp logs show -n mcp -g $RG --follow                  # logs du serveur MCP
az containerapp logs show -n ui  -g $RG --follow                  # logs de l'interface
az containerapp logs show -n api -g $RG --type system             # démarrage, crash, mise à l'échelle
az containerapp revision list -n api -g $RG -o table              # versions déployées
az containerapp job execution list -n ingest -g $RG -o table      # exécutions du Job
```

`logs show` lit les logs d'un réplica en marche : si l'app est à 0 réplica, ouvrez d'abord
l'interface pour la réveiller. L'historique complet (et les logs du Job) est dans le portail
Azure → *Log Analytics* `customer-agent-logs` → *Logs*, avec la requête :
`ContainerAppConsoleLogs_CL | where ContainerAppName_s == "api" | order by TimeGenerated desc`

| Symptôme                                              | Cause probable                                                   | Que faire                                                          |
|-------------------------------------------------------|------------------------------------------------------------------|--------------------------------------------------------------------|
| UI : « L'API n'est pas joignable. »                   | l'app `api` ne démarre pas                                       | `logs show -n api --type system`, vérifier les secrets             |
| UI : « Email ou mot de passe incorrect. »             | l'utilisateur a été créé dans le MongoDB local, pas dans Atlas   | refaire l'étape 2 avec `$env:MONGO_URI`                            |
| Chat : « L'assistant a échoué » (502)                 | clé ou adresse du LLM incorrecte                                 | `logs show -n api`, vérifier `llmApiKey`                           |
| Réponse toujours « Je n'ai rien trouvé... »           | pas de données chargées, `mcp` injoignable, ou clé Voyage fausse | étape 2 ou 8 ; chercher `MCP server unreachable` dans les logs api |
| `ServerSelectionTimeoutError` dans les logs           | Atlas refuse la connexion                                        | Network Access : `0.0.0.0/0` (étape 1)                             |
| Ingestion et recherches très lentes, erreurs `429`    | Voyage AI sans moyen de paiement (3 requêtes/minute)             | ajouter un moyen de paiement sur Voyage                            |
| Première requête lente (quelques secondes)            | réveil des conteneurs (scale to zero)                            | normal ; ou `minReplicas: 1` pour `ui`/`api` (payant en continu)   |
| `MissingSubscriptionRegistration` au déploiement      | fournisseurs Azure non enregistrés                               | étape 3                                                            |
| `az acr build` refusé                                 | restriction de l'abonnement                                      | build local avec Docker (étape 4)                                  |

---

## 10. Coûts et suppression

| Ressource                     | Coût                                                                         |
|-------------------------------|------------------------------------------------------------------------------|
| Container Apps (Consumption)  | payé à l'usage ; à 0 réplica, pas de coût de calcul ; une part gratuite chaque mois |
| Container Registry Basic      | petit coût fixe (environ 5 $/mois)                                           |
| Log Analytics                 | au volume de logs (faible ici)                                               |
| MongoDB Atlas M0              | gratuit                                                                      |
| Lightning AI, Voyage AI       | à la requête                                                                 |

Les prix changent : vérifiez-les sur les pages de tarifs officielles.

**Tout supprimer** (et arrêter tous les coûts Azure) :

```powershell
az group delete -n $RG --yes
```

Le cluster MongoDB Atlas se supprime à part, dans l'interface Atlas.

---

## 11. Pour aller plus loin

- **Secrets** : les mettre dans **Azure Key Vault** et utiliser une **identité managée** pour le
  registre (au lieu de `params.json` et de l'utilisateur admin de l'ACR).
- **Connexion d'entreprise** : **Microsoft Entra ID** au lieu des mots de passe gérés par l'app.
  Seuls deux endroits lisent les tokens : `get_current_user()` dans `api/dependencies.py` et
  `get_account_id()` dans `mcp_server/server.py`.
- **CI/CD** : GitHub Actions qui lance `pytest` à chaque push, puis `az acr build` +
  `az containerapp update` sur la branche principale.
- **Nom de domaine** personnalisé et certificat sur l'app `ui`.
- **Très gros comptes** : passer la recherche par le sens sur Atlas Vector Search
  (seule fonction à changer : `semantic_search` dans `shared/search.py`).

---

## Checklist

- [ ] Atlas : cluster, utilisateur, `0.0.0.0/0`, adresse copiée
- [ ] Données chargées et utilisateur créé (étape 2)
- [ ] `az login`, fournisseurs enregistrés, groupe de ressources créé
- [ ] Registre créé, image `customer-agent:1` construite
- [ ] `infra/params.json` rempli (et jamais commité)
- [ ] `az deployment group create` réussi
- [ ] Interface ouverte, connexion OK, une question posée
