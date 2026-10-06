"""Configuration de l'application.

RÔLE
    Rassembler TOUS les réglages du projet (adresses, clés API, limites...) dans un seul
    objet `settings`, au lieu d'écrire des valeurs en dur partout dans le code.

D'OÙ VIENNENT LES VALEURS ? (par ordre de priorité, la première trouvée gagne)
    1. les variables d'environnement           ex. : $env:MONGO_URI = "..." (PowerShell)
    2. le fichier .env du dossier courant       ex. : MONGO_URI=mongodb://localhost:27017
    3. la valeur par défaut écrite ci-dessous

    Le nom de la variable = le nom du champ en MAJUSCULES : `mongo_uri` <- MONGO_URI.
    Sur Azure, ces variables sont définies dans infra/main.bicep (liste `envVars`).

UTILISATION (partout dans le code)
    from shared.config import settings
    print(settings.mongo_uri)
"""

# pydantic-settings lit automatiquement les variables d'environnement et le .env,
# et convertit les valeurs dans le bon type (ex. "8001" -> 8001 pour un champ `int`).
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_file=".env"  : lire aussi le fichier .env (s'il existe) du dossier où on lance Python
    # extra="ignore"   : ignorer les variables du .env qui ne correspondent à aucun champ
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ------------------------------------------------------------------ MongoDB
    # Adresse du serveur MongoDB. En local : docker compose ; sur Azure : MongoDB Atlas.
    mongo_uri: str = "mongodb://localhost:27017"
    # Nom de la base de données (les tests en utilisent une autre, créée puis supprimée).
    db_name: str = "account_memory"

    # --------------------------------------------------------------- Tokens JWT
    # Clé secrète qui SIGNE les tokens. Le même secret est utilisé par :
    #   - l'API (api/)          qui CRÉE les tokens au login,
    #   - le serveur MCP        qui les VÉRIFIE à chaque appel d'outil.
    # Vide par défaut : security.get_secret() refuse de fonctionner tant qu'il n'est pas défini.
    jwt_secret: str = ""
    # Durée de vie d'un token : 480 minutes = 8 heures (une journée de travail).
    jwt_expire_minutes: int = 480

    # ------------------------------------------------------- Modèle de chat (LLM)
    # N'importe quelle API "compatible OpenAI" (Lightning AI, Azure OpenAI, OpenAI, Ollama...).
    # Changer de fournisseur = changer ces 3 valeurs, sans toucher au code (voir agent/llm.py).
    llm_base_url: str = "https://lightning.ai/api/v1/"
    llm_api_key: str = ""
    chat_model: str = "lightning-ai/gemma-4-31B-it"

    # ------------------------------------------------------ Embeddings (Voyage AI)
    voyage_api_key: str = ""
    embedding_url: str = "https://api.voyageai.com/v1/embeddings"
    embedding_model: str = "voyage-4-large"
    # Taille des vecteurs : 256 nombres par texte. Plus petit = moins de place en base
    # et calcul de similarité plus rapide, pour une qualité de recherche encore très bonne.
    embedding_dimensions: int = 256

    # ------------------------------------------------------------- Serveur MCP
    # L'adresse que l'AGENT appelle pour utiliser les outils de recherche.
    # En local : http://localhost:8001/mcp ; sur Azure : https://mcp.internal.<domaine>/mcp
    mcp_url: str = "http://localhost:8001/mcp"
    # Le port sur lequel le SERVEUR MCP écoute (utilisé par mcp_server/server.py).
    mcp_port: int = 8001

    # ------------------------------------------------------------------- Agent
    # Taille maximale (en caractères) de l'ensemble des sources envoyées au LLM.
    # Limite le coût, la latence, et évite de dépasser la fenêtre de contexte du modèle.
    context_chars: int = 12000
    # Les conversations (mémoire LangGraph) sont supprimées automatiquement après 30 jours.
    conversation_ttl_days: int = 30

    # -------------------------------------------------- Envoi d'emails (optionnel)
    # Si SMTP_HOST est vide, un email approuvé n'est PAS envoyé : il est rangé dans la
    # collection MongoDB "outbox" (pratique pour une démo). Voir actions/email_sender.py.
    smtp_host: str = ""
    smtp_port: int = 587  # 587 = port SMTP standard avec chiffrement STARTTLS
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "assistant@example.com"


# L'objet unique, créé UNE fois au premier import de ce module.
# Tous les autres fichiers importent CET objet (ils ne recréent jamais un Settings()).
settings = Settings()
