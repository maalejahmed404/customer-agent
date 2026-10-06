# Le projet et ses choix techniques

## Le projet en un paragraphe

Customer Agent est un assistant pour une équipe commerciale. Un commercial se connecte,
choisit implicitement un compte client (celui de son login), et pose des questions en
langage naturel sur les appels et les emails de ce client : *« Qu'a dit le client sur le
prix ? »*, *« Écris une relance à Hélène »*. L'assistant cherche dans les données du
compte, répond **uniquement** à partir de ce qu'il a trouvé, **cite ses sources**, se
souvient de la conversation, et peut rédiger un email qui **n'est jamais envoyé sans
l'accord d'un humain**.

## Comment ça marche, en un paragraphe

Les appels et emails sont chargés une fois dans MongoDB, découpés en petits morceaux,
chacun accompagné d'un vecteur de sens (embedding). Quand une question arrive, l'API
vérifie le token de l'utilisateur, puis lance un agent LangGraph en 4 étapes : un
**planner** (le LLM décide quoi chercher), un **retriever** (les recherches partent en
parallèle vers un serveur MCP qui interroge MongoDB), un **responder** (le LLM répond en
citant les sources) et, si demandé, un **email_drafter** (le LLM rédige un email mis en
attente de validation). L'interface Streamlit affiche la réponse, les sources et les
emails à approuver.

```
Navigateur → ui (Streamlit) → api (FastAPI + agent LangGraph) → mcp (outils) → MongoDB
                                         ↓
                                   LLM (Lightning AI)          Embeddings : Voyage AI
```

---

## Les choix, et pourquoi

### 1. Architecture de l'agent

**Planifier puis chercher, plutôt qu'un agent qui boucle (ReAct).**
Un agent ReAct rappelle le LLM après chaque résultat d'outil : le nombre d'appels, donc
le temps et le coût, dépendent de ce que le modèle décide. Ici, il y a toujours **deux
appels LLM** (planifier, répondre) et toutes les recherches partent **en même temps**. Le
temps de réponse est prévisible et chaque étape est une petite fonction testable seule.
Contrepartie : l'agent ne peut pas relancer une recherche au vu de ce qu'il vient de
trouver. Pour des questions sur un seul compte, un bon plan suffit.

**LangGraph.**
Le déroulé pourrait s'écrire en fonctions Python simples. LangGraph apporte deux choses
qu'on n'a pas à coder : les **embranchements** (pas de recherche pour « Bonjour », pas
d'email si on n'en demande pas) et surtout la **mémoire des conversations** : son
checkpointer MongoDB sauvegarde l'état après chaque étape, ce qui permet les questions de
relance (*« et le prix ? »*).

**Une conversation par utilisateur.**
L'identifiant de conversation est construit par l'API à partir du **token** :
`compte:email:conversation`. Un autre utilisateur qui envoie le même identifiant tombe
sur une autre conversation. Seules les questions et réponses sont mémorisées (pas les
sources), et elles sont supprimées après 30 jours.

**Sortie structurée pour le plan et l'email.**
Au lieu de demander du texte libre au LLM puis de l'analyser, on lui donne un
« formulaire » (modèles pydantic `Plan` et `EmailDraft`). La réponse est directement un
objet vérifié. Si le LLM échoue, on cherche avec la question telle quelle : l'utilisateur
a toujours une réponse.

### 2. Recherche

**Mots-clés ET sens, fusionnés.**
Les deux se trompent dans des cas différents. Les mots-clés trouvent l'exact
(`FAC-2291`, un nom de produit, un montant) mais ratent les synonymes. Le sens trouve
« la facture est contestée » pour « problème de facturation », mais peut rater un numéro
précis. Les deux ensemble couvrent les deux cas.

**Fusion par le rang (Reciprocal Rank Fusion).**
Le score texte de MongoDB et le score cosinus n'ont pas la même échelle, on ne peut pas
les additionner. On fusionne donc sur le **rang** : un passage trouvé par plusieurs
recherches passe devant. Simple, sans réglage, et standard.

**Découpage en morceaux de ~1 200 caractères, chevauchement de 200.**
Un appel entier mélange plusieurs sujets : son vecteur serait flou et l'envoyer entier au
LLM coûterait cher. Des morceaux courts sont précis ; le chevauchement évite de couper une
idée en deux. Le résumé d'un appel devient son propre morceau, utile pour les questions
générales. Chaque morceau garde le lien vers son appel ou email : c'est ce qui permet de
**citer et d'ouvrir la source**.

**Similarité calculée avec numpy, sans index vectoriel.**
Un compte a quelques centaines de morceaux : le calcul exact prend quelques millisecondes
et il est toujours juste. Un index vectoriel ajouterait de la configuration pour aucun
gain à cette taille. Si un compte devient énorme, une seule fonction change
(`semantic_search`, vers Atlas Vector Search).

**Budget de 12 000 caractères de sources.**
Limite le coût et la latence du LLM, et garantit de ne jamais dépasser sa fenêtre de
contexte.

### 3. MCP pour les outils

Pour notre agent seul, de simples fonctions Python suffiraient. MCP est un **standard** :
les outils de recherche deviennent utilisables par **n'importe quel client MCP** (Claude
Desktop, Copilot Studio, l'agent d'une autre équipe) sans écrire une API pour chacun.
`examples/mcp_client_example.py` le prouve. Le serveur MCP tourne dans son propre
conteneur, monte en charge seul, et **vérifie lui-même le token** : même ouvert à
l'extérieur, un client ne voit que son compte.

### 4. Données et modèles

**MongoDB.**
Appels et emails ont des formes différentes : une base de documents les stocke
naturellement, dans une seule collection (champ `kind`), donc « tout sur ce compte en
mars » est une seule requête. MongoDB apporte aussi un index texte **en français**
(« facture » trouve « facturées ») et LangGraph a un checkpointer MongoDB officiel.
Une seule base pour tout : données, utilisateurs, actions, conversations. PostgreSQL +
pgvector aurait été un choix tout aussi valable.

**LLM via une API compatible OpenAI (Gemma 4 sur Lightning AI).**
Presque tous les fournisseurs parlent ce format. Changer de fournisseur (Azure OpenAI,
OpenAI...) = changer trois variables d'environnement, jamais le code. Température à 0 :
réponses stables et factuelles.

**Embeddings Voyage AI (256 dimensions).**
Un modèle fait pour la recherche, avec des vecteurs courts (moins de place, calcul plus
rapide). Documents et questions sont encodés différemment, comme Voyage le recommande.

**Modèles hébergés plutôt qu'un serveur GPU.**
Payés à la requête. Un GPU tournerait (et coûterait) en permanence, ce qui annulerait
l'intérêt de tout éteindre la nuit.

### 5. Sécurité

**Le compte vient uniquement du token JWT.**
Jamais du corps d'une requête, jamais d'un argument d'outil. Chaque requête MongoDB
commence par `account_id`. Un utilisateur du compte 2 ne peut rien lire, lister ni
approuver du compte 1 : c'est vérifié par des tests à chaque niveau (base, MCP, API).

**Mots de passe hachés (PBKDF2, 200 000 tours, sel aléatoire).**
Le mot de passe n'est jamais stocké ; un vol de la base ne le révèle pas.

**Protection contre l'injection de prompt.**
Les emails sont écrits par des inconnus et peuvent contenir *« ignore tes instructions »*.
Leur texte est traité comme une **donnée** : placé dans le message utilisateur (jamais le
prompt système), entre des marqueurs aléatoires impossibles à imiter, nettoyé des
caractères invisibles. Et surtout, le modèle **n'a aucun pouvoir d'agir** : outils en
lecture seule, et il ne peut que proposer un email.

**Validation humaine de chaque email.**
L'agent enregistre l'email en `pending` ; seul un humain du même compte l'approuve via
l'API, en voyant le destinataire. Le changement de statut est atomique : un double clic
n'envoie pas deux fois. Sans SMTP configuré, l'email va dans une collection `outbox` au
lieu d'être envoyé (démo sans risque).

### 6. Code et organisation

**Un dossier par rôle, un dossier de service = une ressource Azure.**
`ui/`, `api/`, `mcp_server/`, `ingestion/` correspondent chacun à ce qui tourne sur Azure ;
`shared/` contient le code commun. On sait immédiatement où chercher.

**Tout en asynchrone.**
MongoDB, Voyage et MCP sont appelés avec `async` : quand l'agent lance trois recherches,
elles attendent **en même temps** au lieu de l'une après l'autre (vérifié par un test).

**49 tests, sans clé API.**
Le LLM et les embeddings sont remplacés par des faux (`tests/fakes.py`) : les tests sont
gratuits, rapides et donnent toujours le même résultat. Ils utilisent un vrai MongoDB car
la recherche par mots-clés dépend de son index texte.

### 7. Déploiement sur Azure

**Azure Container Apps pour `ui`, `api` et `mcp`.**
L'usage est en rafales (heures de bureau, rien la nuit) : chaque app peut **descendre à
0** quand personne ne l'utilise, donc ne rien coûter en calcul. HTTPS, accès interne (seule
l'interface est publique) et mise à l'échelle sont inclus, sans cluster à gérer.
Contrepartie : quelques secondes d'attente au premier appel après une pause (évitable avec
`minReplicas: 1`, payé en continu).

**Pourquoi pas les autres services.**
*Azure Functions* exécute du code court déclenché par un événement : impossible pour
Streamlit (serveur permanent + WebSocket) et mal adapté à l'agent (réponse HTTP limitée à
230 s, démarrages à froid lents avec de grosses librairies). Il reste le bon choix pour de
futurs connecteurs Outlook/Teams. *App Service* marcherait mais est payé en continu.
*AKS* serait un cluster Kubernetes à maintenir pour trois conteneurs. *Des machines
virtuelles* obligeraient à tout gérer soi-même.

**Streamlit pour l'interface.**
Une interface de chat en Python pur, en une centaine de lignes, sans JavaScript. Suffisant
pour un outil interne. Si l'outil devient un produit, les évolutions naturelles sont un
front React (sur Static Web Apps) ou un bot Teams, branchés sur la même API.

**Une seule image Docker pour tout.**
Un seul build, une seule version : les quatre services ont toujours le même code ; seule la
commande de démarrage change. L'image qui tourne en local avec `docker compose` est celle
déployée.

**Le chargement des données en Job.**
L'ingestion est ponctuelle et peut durer plus d'une heure (limite de débit de Voyage) : un
Container Apps Job démarre, charge, s'arrête. Elle est idempotente : on peut la relancer
sans créer de doublons.

**MongoDB Atlas hors d'Azure.**
Le niveau gratuit suffit pour démarrer et c'est la seule partie allumée en permanence.

**Infrastructure décrite en Bicep.**
Tout l'environnement est dans un fichier (`infra/main.bicep`) : reproductible, versionné,
recréable en une commande. Les secrets sont des secrets Container Apps, jamais en clair.

---

## Limites connues et prochaines étapes

- **Connexion d'entreprise** : utilisateurs gérés par l'app aujourd'hui ; en entreprise,
  Microsoft Entra ID. Seules deux fonctions lisent les tokens, c'est là qu'on changerait.
- **Données en continu** : l'ingestion part de fichiers ; la suite est des connecteurs
  Outlook/Teams (Azure Functions) qui appellent la même fonction d'ingestion.
- **Qualité des réponses** : les tests vérifient la mécanique avec un faux LLM ; mesurer la
  qualité demande un jeu de questions réelles avec les réponses attendues.
- **Production** : secrets dans Key Vault, identité managée, IP de sortie fixe pour Atlas,
  CI/CD, séparation dev/prod (détails dans `DEPLOIEMENT_AZURE.md`).
- **Réponses en streaming** : aujourd'hui la réponse arrive d'un bloc ; l'afficher mot à
  mot rendrait les longues réponses plus agréables.
