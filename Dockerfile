# Image unique pour ui, api, mcp et ingest : la commande de démarrage sélectionne le service.
FROM python:3.12-slim

WORKDIR /srv

# Dépendances en premier pour profiter du cache de couches.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY ingestion ./ingestion
COPY mcp_server ./mcp_server
COPY agent ./agent
COPY actions ./actions
COPY api ./api
COPY scripts ./scripts
COPY ui ./ui

# Jeu de données embarqué pour le job d'ingestion.
COPY data ./data

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
