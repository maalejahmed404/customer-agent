"""Configuration de l'application, exposée par l'objet unique `settings`.

Priorité des sources : variables d'environnement, puis fichier .env, puis valeurs par défaut.
Sur Azure, les variables sont déclarées dans infra/main.bicep (`envVars`).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ------------------------------------------------------------------ MongoDB
    mongo_uri: str = "mongodb://localhost:27017"
    db_name: str = "account_memory"

    # --------------------------------------------------------------- Tokens JWT
    # Secret partagé entre l'API (émission) et le serveur MCP (vérification).
    # Vide par défaut : security.get_secret() refuse de démarrer tant qu'il n'est pas défini.
    jwt_secret: str = ""
    jwt_expire_minutes: int = 480

    # ------------------------------------------------------- Modèle de chat (LLM)
    # Tout endpoint compatible OpenAI : changer de fournisseur ne demande aucun changement de code.
    llm_base_url: str = "https://lightning.ai/api/v1/"
    llm_api_key: str = ""
    chat_model: str = "lightning-ai/gemma-4-31B-it"

    # ------------------------------------------------------ Embeddings (Voyage AI)
    voyage_api_key: str = ""
    embedding_url: str = "https://api.voyageai.com/v1/embeddings"
    embedding_model: str = "voyage-4-large"
    # Dimension réduite : stockage et calcul de similarité moins coûteux.
    embedding_dimensions: int = 256

    # ------------------------------------------------------------- Serveur MCP
    # mcp_url : adresse appelée par l'agent ; mcp_port : port d'écoute du serveur.
    mcp_url: str = "http://localhost:8001/mcp"
    mcp_port: int = 8001

    # ------------------------------------------------------------------- Agent
    # Taille maximale (en caractères) des sources envoyées au LLM.
    context_chars: int = 12000
    conversation_ttl_days: int = 30

    # -------------------------------------------------- Envoi d'emails (optionnel)
    # Sans SMTP_HOST, un email approuvé est rangé dans la collection "outbox" au lieu d'être envoyé.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "assistant@example.com"


settings = Settings()
