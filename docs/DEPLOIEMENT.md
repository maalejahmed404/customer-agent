# Conception du déploiement Azure

Ce document décrit la cible de déploiement de Customer Agent, les décisions
d'infrastructure et la procédure pour la reproduire. L'ensemble est défini dans
[`infra/main.bicep`](../infra/main.bicep).

## 1. Objectifs et contraintes

| Contrainte | Traduction technique |
|------------|----------------------|
| Usage en rafales : heures de bureau, rien la nuit | mise à l'échelle à zéro sur tous les services |
| Outil interne, équipe réduite | plateforme managée, aucun cluster à exploiter |
| Seule l'interface doit être joignable depuis Internet | `api` et `mcp` en ingress interne |
| Environnement recréable à l'identique | infrastructure décrite en Bicep, une seule image |
| Budget minimal | palier Consumption, base Atlas M0, modèles facturés à la requête |

## 2. Topologie

```
                                Internet
                                   │ HTTPS
                                   ▼
┌──────────────── Environnement Container Apps « customer-agent-env » ────────────────┐
│                                                                                     │
│   ui (public, 8501) ──► api (interne, 8000) ──► mcp (interne, 8001)                 │
│   Streamlit             FastAPI + agent          FastMCP                            │
│                                                                                     │
│   ingest (job manuel)                                                               │
└─────────────────────────────────────────────────────────────────────────────────────┘
   Container Registry : image unique            Log Analytics : journaux (30 jours)

Services externes
   MongoDB Atlas   ◄── api, mcp, ingest
   LLM             ◄── api
   Voyage AI       ◄── mcp, ingest
```

| Ressource | Type | Exposition | Commande |
|-----------|------|------------|----------|
| `ui` | Container App | publique, sessions persistantes | `streamlit run ui/streamlit_app.py` |
| `api` | Container App | interne | `uvicorn api.main:app` |
| `mcp` | Container App | interne (publique si `exposeMcp`) | `python -m mcp_server.server` |
| `ingest` | Container Apps Job | aucune | `python -m ingestion.ingest data/accounts` |

Chaque app dispose de 0,5 vCPU et 1 Gio, de 0 à 3 réplicas, avec une règle HTTP à 20
requêtes simultanées par réplica.

## 3. Décisions

### 3.1 Azure Container Apps

Le trafic attendu est intermittent. Container Apps permet de descendre chaque service à
zéro réplica, fournit HTTPS, la découverte de services interne et la mise à l'échelle sans
cluster à administrer.

| Alternative | Raison de l'écarter |
|-------------|---------------------|
| Azure Functions | modèle événementiel à exécution courte : inadapté à Streamlit (processus persistant, WebSocket) et à un agent dont la réponse peut être longue ; reste pertinent pour de futurs connecteurs Outlook/Teams |
| App Service | fonctionnerait, mais facturé en continu |
| AKS | un cluster Kubernetes à maintenir pour trois conteneurs |
| Machines virtuelles | système, TLS et mise à l'échelle à gérer soi-même |

**Compromis.** Démarrage à froid de quelques secondes après une période d'inactivité.
`minReplicas: 1` sur `ui` et `api` le supprime, au prix d'une facturation continue.

### 3.2 Une image, plusieurs commandes

Les quatre charges de travail utilisent la même image ; seule la commande de démarrage
change. Un seul build à produire, et aucune dérive de version possible entre l'API et le
serveur MCP, qui partagent `shared/`. L'image exécutée localement par `docker compose` est
celle qui est déployée.

**Compromis.** L'image embarque les dépendances de tous les services (Streamlit dans le
conteneur `mcp`, par exemple). J'ai préféré la simplicité de livraison à la taille d'image.

### 3.3 L'agent dans le conteneur `api`, le serveur MCP à part

L'agent est une bibliothèque appelée par `POST /chat`, pas un service : le séparer
ajouterait un saut réseau sans bénéfice à cette échelle. Il monte en charge avec l'API.

Le serveur MCP est isolé pour deux raisons : il doit pouvoir être exposé à d'autres clients
indépendamment de l'API, et sa charge suit le nombre de recherches en parallèle, pas le
nombre de requêtes de chat.

### 3.4 Surface réseau minimale

Seule `ui` a un ingress externe. `api` n'est joignable que depuis l'environnement, à
l'adresse `api.internal.<domaine>`. Le paramètre `exposeMcp` ouvre le serveur MCP à des
clients externes ; chaque appel reste authentifié par jeton et limité au compte du jeton.

`ui` utilise l'affinité de session : Streamlit maintient une connexion WebSocket par
utilisateur, qui doit rester sur le même réplica.

### 3.5 L'ingestion en job

L'ingestion est ponctuelle et peut dépasser la durée raisonnable d'une requête HTTP. Un
Container Apps Job démarre, traite, puis s'arrête (délai maximal d'une heure, une
relance). L'ingestion étant idempotente, relancer un job interrompu reprend sans doublon.

### 3.6 MongoDB Atlas hors d'Azure

Le palier M0 est gratuit et suffisant pour ce volume. C'est le seul composant actif en
permanence.

**Compromis.** Container Apps en mode Consumption n'a pas d'adresse IP de sortie fixe :
l'accès réseau Atlas est ouvert à `0.0.0.0/0` et la protection repose sur les identifiants.
C'est l'écart le plus important par rapport à une cible de production (§8).

### 3.7 Infrastructure en Bicep

L'environnement entier tient dans un fichier versionné et se recrée en une commande. Les
valeurs sensibles sont des paramètres `@secure()` injectés comme secrets Container Apps et
référencés par `secretRef`, jamais en clair dans la définition des conteneurs.

## 4. Configuration

| Variable | Secret | Consommée par | Rôle |
|----------|--------|---------------|------|
| `MONGO_URI` | oui | api, mcp, ingest | connexion Atlas |
| `JWT_SECRET` | oui | api, mcp | signature (api) et vérification (api, mcp) des jetons |
| `LLM_API_KEY` | oui | api | clé du fournisseur LLM |
| `LLM_BASE_URL`, `CHAT_MODEL` | non | api | endpoint compatible OpenAI et modèle |
| `VOYAGE_API_KEY` | oui | mcp, ingest | clé des embeddings |
| `EMBEDDING_MODEL` | non | mcp, ingest | modèle d'embeddings |
| `MCP_URL` | non | api | adresse interne du serveur MCP |
| `API_URL` | non | ui | adresse interne de l'API |
| `SMTP_*` | oui | api | optionnel ; sans SMTP, les emails approuvés vont dans `outbox` |

`api` et `mcp` partagent `JWT_SECRET` : l'agent émet un jeton au nom de l'utilisateur pour
appeler le serveur MCP, qui le vérifie indépendamment.

## 5. Procédure de déploiement

Prérequis : un abonnement Azure, Azure CLI, un cluster MongoDB Atlas, les clés du
fournisseur LLM et de Voyage AI. Les commandes sont en PowerShell, depuis la racine du
dépôt.

```powershell
$RG  = "customer-agent"
$LOC = "francecentral"

# Préparation de l'abonnement (une fois)
az login
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.ContainerRegistry
az extension add --name containerapp
az group create -n $RG -l $LOC

# Registre et image
$ACR = "customeragent$(Get-Random -Maximum 99999)"
az acr create -g $RG -n $ACR --sku Basic --admin-enabled true
az acr build -r $ACR -t customer-agent:1 .

# Paramètres : copier le modèle, le renseigner, déployer
copy infra\params.example.json infra\params.json
az deployment group create -g $RG -f infra/main.bicep -p "@infra/params.json"
az deployment group show -g $RG -n main --query properties.outputs -o json
```

`infra/params.json` contient des secrets et est exclu du dépôt. Les sorties du déploiement
donnent l'URL publique de l'interface et les adresses internes de `api` et `mcp`.

**Données initiales.** Soit depuis un poste, en pointant `MONGO_URI` vers Atlas :

```powershell
$env:MONGO_URI = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/"
python -m ingestion.ingest data/accounts/account_1.json
python -m scripts.create_user <email> "<mot de passe>" 1
```

Soit avec le job, qui charge tous les comptes embarqués dans l'image :

```powershell
az containerapp job start -g $RG -n ingest
```

Sur les abonnements où `az acr build` est indisponible, l'image se construit localement
(`az acr login`, `docker build`, `docker push`).

## 6. Livraison d'une nouvelle version

Chaque version porte un nouveau tag d'image : à tag identique, Container Apps ne crée pas
de révision.

```powershell
az acr build -r $ACR -t customer-agent:2 .
# mettre à jour "image" dans infra/params.json, puis :
az deployment group create -g $RG -f infra/main.bicep -p "@infra/params.json"
```

Redéployer le Bicep est la voie de référence : la configuration appliquée reste celle du
dépôt. Une modification faite directement avec `az containerapp update` est écrasée au
déploiement suivant.

## 7. Exploitation

**Journaux.** Les sorties des conteneurs sont centralisées dans Log Analytics, conservées
30 jours.

```powershell
az containerapp logs show -n api -g $RG --follow          # application
az containerapp logs show -n api -g $RG --type system     # démarrages, mise à l'échelle
az containerapp job execution list -n ingest -g $RG -o table
```

```kusto
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "api"
| order by TimeGenerated desc
```

**Diagnostic.**

| Symptôme | Cause la plus probable |
|----------|------------------------|
| L'interface ne joint pas l'API | `api` ne démarre pas (voir les journaux système) ou secret manquant |
| `502` sur `/chat` | clé ou endpoint LLM invalide |
| Réponses systématiquement vides | aucune donnée ingérée, `mcp` injoignable ou clé Voyage invalide |
| `ServerSelectionTimeoutError` | accès réseau Atlas non ouvert |
| Erreurs `429`, ingestion très lente | limite de débit Voyage sur un compte sans moyen de paiement |
| Première requête lente | démarrage à froid après mise à l'échelle à zéro |

**Coûts.**

| Poste | Modèle de facturation |
|-------|-----------------------|
| Container Apps (Consumption) | à l'usage, nul à zéro réplica |
| Container Registry (Basic) | forfait mensuel fixe |
| Log Analytics | au volume ingéré |
| MongoDB Atlas M0 | gratuit |
| LLM et embeddings | à la requête |

`az group delete -n $RG --yes` supprime toutes les ressources Azure. Le cluster Atlas se
supprime séparément.

## 8. Écarts par rapport à une cible de production

Ce déploiement est dimensionné pour une démonstration. Ce que je changerais avant une mise
en production, par ordre de priorité :

| Écart | Cible |
|-------|-------|
| Atlas ouvert à `0.0.0.0/0` | environnement Container Apps dans un VNet avec NAT Gateway (IP de sortie fixe) ou Private Endpoint Atlas |
| Secrets dans un fichier de paramètres local | Azure Key Vault, référencé par les Container Apps |
| Utilisateur admin du registre | identité managée avec le rôle `AcrPull` |
| Comptes gérés par l'application | Microsoft Entra ID |
| Pas de sondes de santé déclarées | sondes de démarrage et de vivacité sur `/health`, déjà exposé par `api` et `mcp` |
| Déploiement manuel | pipeline GitHub Actions : tests, build, déploiement Bicep sur la branche principale |
| Un seul environnement | environnements distincts de recette et de production |
| Journaux uniquement | traces et métriques applicatives (latence par nœud du graphe, taux d'échec du LLM) |
