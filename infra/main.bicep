// Azure Container Apps : ui (publique), api et mcp (internes), job d'ingestion.
// Une seule image pour les quatre. MongoDB Atlas, le LLM et Voyage AI sont externes
// et passés en paramètres. Conception : docs/DEPLOIEMENT.md

param location string = resourceGroup().location

// ----------------------------------------------------------------- paramètres
@description('Nom complet de l image, ex. monregistre.azurecr.io/customer-agent:1')
param image string
param registryServer string
param registryUsername string
@secure()
param registryPassword string

@secure()
param mongoUri string
@secure()
param jwtSecret string
@secure()
param llmApiKey string
param llmBaseUrl string = 'https://lightning.ai/api/v1/'
param chatModel string = 'lightning-ai/gemma-4-31B-it'
@secure()
param voyageApiKey string
param embeddingModel string = 'voyage-4-large'

@description('Rendre le serveur MCP accessible depuis Internet (Claude Desktop, Copilot Studio...). Désactivé par défaut.')
param exposeMcp bool = false

// ----------------------------------------------------------------- logs
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'customer-agent-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ----------------------------------------------------------------- environnement
resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'customer-agent-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// Adresses des apps : une app interne est jointe à <app>.internal.<domaine>,
// une app publique à <app>.<domaine>.
var domain = env.properties.defaultDomain
var mcpHost = exposeMcp ? 'mcp.${domain}' : 'mcp.internal.${domain}'

// ----------------------------------------------------------------- réglages communs
var secrets = [
  { name: 'registry-password', value: registryPassword }
  { name: 'mongo-uri', value: mongoUri }
  { name: 'jwt-secret', value: jwtSecret }
  { name: 'llm-api-key', value: llmApiKey }
  { name: 'voyage-api-key', value: voyageApiKey }
]

var registries = [
  { server: registryServer, username: registryUsername, passwordSecretRef: 'registry-password' }
]

var envVars = [
  { name: 'MONGO_URI', secretRef: 'mongo-uri' }
  { name: 'JWT_SECRET', secretRef: 'jwt-secret' }
  { name: 'LLM_API_KEY', secretRef: 'llm-api-key' }
  { name: 'LLM_BASE_URL', value: llmBaseUrl }
  { name: 'CHAT_MODEL', value: chatModel }
  { name: 'VOYAGE_API_KEY', secretRef: 'voyage-api-key' }
  { name: 'EMBEDDING_MODEL', value: embeddingModel }
  { name: 'MCP_URL', value: 'https://${mcpHost}/mcp' }               // utilisé par l'agent (api)
  { name: 'API_URL', value: 'https://api.internal.${domain}' }       // utilisé par l'interface (ui)
]

// 0 réplica quand personne n'utilise l'app ; +1 réplica par tranche de 20 requêtes simultanées.
var scaleToZero = {
  minReplicas: 0
  maxReplicas: 3
  rules: [
    { name: 'http', http: { metadata: { concurrentRequests: '20' } } }
  ]
}

var resources = {
  cpu: json('0.5')
  memory: '1Gi'
}

// ----------------------------------------------------------------- app "mcp"
resource mcp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'mcp'
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      // Interne par défaut. Avec exposeMcp, d'autres clients MCP peuvent le joindre ;
      // chaque appel demande quand même le token d'un utilisateur et ne voit que son compte.
      ingress: { external: exposeMcp, targetPort: 8001 }
      secrets: secrets
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'mcp'
          image: image
          command: [ 'python', '-m', 'mcp_server.server' ]
          env: envVars
          resources: resources
        }
      ]
      scale: scaleToZero
    }
  }
}

// ----------------------------------------------------------------- app "api" (+ agent LangGraph)
resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'api'
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: false, targetPort: 8000 }   // interne : seule l'app ui l'appelle
      secrets: secrets
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          command: [ 'uvicorn', 'api.main:app', '--host', '0.0.0.0', '--port', '8000' ]
          env: envVars
          resources: resources
        }
      ]
      scale: scaleToZero
    }
  }
}

// ----------------------------------------------------------------- app "ui" (publique)
resource ui 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ui'
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      // Point d'entrée public. Streamlit garde une connexion websocket par utilisateur :
      // les "sticky sessions" gardent chaque utilisateur sur le même réplica.
      ingress: {
        external: true
        targetPort: 8501
        stickySessions: { affinity: 'sticky' }
      }
      secrets: secrets
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'ui'
          image: image
          command: [ 'streamlit', 'run', 'ui/streamlit_app.py', '--server.address', '0.0.0.0', '--server.port', '8501' ]
          env: envVars
          resources: resources
        }
      ]
      scale: scaleToZero
    }
  }
}

// ----------------------------------------------------------------- job "ingest"
resource ingest 'Microsoft.App/jobs@2024-03-01' = {
  name: 'ingest'
  location: location
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 3600
      replicaRetryLimit: 1
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      secrets: secrets
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'ingest'
          image: image
          command: [ 'python', '-m', 'ingestion.ingest', 'data/accounts' ]
          env: envVars
          resources: resources
        }
      ]
    }
  }
}

// ----------------------------------------------------------------- sorties
output url string = 'https://${ui.properties.configuration.ingress.fqdn}'
output apiUrl string = 'https://api.internal.${domain}'
output mcpUrl string = 'https://${mcpHost}/mcp'
