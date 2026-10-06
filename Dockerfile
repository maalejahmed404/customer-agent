# UNE seule image pour tous les services. C'est la commande de démarrage qui choisit
# ce qui tourne (voir docker-compose.yml en local et infra/main.bicep sur Azure) :
#   ui     -> streamlit run ui/streamlit_app.py ...
#   api    -> uvicorn api.main:app ...              (contient l'agent LangGraph)
#   mcp    -> python -m mcp_server.server
#   ingest -> python -m ingestion.ingest data/accounts
FROM python:3.12-slim

WORKDIR /srv

# 1. Les dépendances d'abord (Docker les garde en cache tant que requirements.txt ne change pas)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Le code
COPY shared ./shared
COPY ingestion ./ingestion
COPY mcp_server ./mcp_server
COPY agent ./agent
COPY actions ./actions
COPY api ./api
COPY scripts ./scripts
COPY ui ./ui

# 3. Les données (pour le Job d'ingestion)
COPY data ./data

# Commande par défaut : l'API
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
