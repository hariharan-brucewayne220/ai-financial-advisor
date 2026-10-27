// AI Financial Advisor API on Azure
//
// One resource group holding:
//   - Container Apps environment (consumption) + the API container app, scale 0..1
//   - Azure Container Registry (Basic) for the API image
//   - Key Vault (RBAC) with SECRET-KEY and DATABASE-URL
//   - Azure Database for PostgreSQL Flexible Server (B1ms) with pgvector allowed
//   - Azure OpenAI with gpt-4o-mini and text-embedding-3-small deployments (keys disabled)
//   - Azure AI Search, Free tier (keys disabled, Entra ID only)
//   - Two user-assigned managed identities:
//       app    -> pulls the image, reads Key Vault, calls Azure OpenAI and AI Search
//       github -> GitHub Actions logs in with OIDC (federated credential, no secret)
//                 and may only push images and update the container app
//
// No keys or passwords live in code or env files. The Postgres admin password
// and JWT secret are generated at deploy time and written straight to Key Vault.

targetScope = 'resourceGroup'

@description('Azure region. Check quota first: az cognitiveservices usage list --location <region> -o table')
param location string = resourceGroup().location

@description('Short lowercase prefix for resource names.')
@maxLength(10)
param prefix string = 'finadv'

@description('GitHub repo allowed to deploy, as owner/name.')
param githubRepo string = 'hariharan-brucewayne220/ai-financial-advisor'

@description('Branch whose pushes may deploy.')
param githubBranch string = 'main'

@description('Object id of the person running the eval locally (az ad signed-in-user show --query id -o tsv). Gets data access to AI Search, Azure OpenAI and Key Vault secrets. Leave empty to skip.')
param operatorPrincipalId string = ''

@description('Public IP allowed through the Postgres firewall for running the eval from a laptop. Leave empty to allow only Azure services.')
param operatorIpAddress string = ''

@description('Container image for the API. The first deploy uses a placeholder until CI pushes the real image.')
param apiImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Port the image listens on (8000 for the API, 80 for the placeholder).')
param apiTargetPort int = 80

@description('pgvector or azure_search')
@allowed(['pgvector', 'azure_search'])
param retrievalBackend string = 'azure_search'

@description('Tokens-per-minute capacity, in thousands, for each model deployment.')
param chatCapacityK int = 10

@description('Deployment SKU for gpt-4o-mini. Standard by default: some subscriptions (e.g. student) have 0 GlobalStandard quota for it.')
@allowed(['Standard', 'GlobalStandard'])
param chatSkuName string = 'Standard'
param embeddingCapacityK int = 10

@description('Deployment SKU for the embedding model. Some regions only offer Standard.')
param embeddingSkuName string = 'Standard'

@secure()
@description('Generated on every infra deploy unless passed in. Re-running infra rotates it; Key Vault gets the new value in the same deployment.')
param postgresAdminPassword string = 'Pg1!${newGuid()}'

@secure()
@description('JWT signing key for the API. Generated unless passed in.')
param jwtSecret string = '${newGuid()}${newGuid()}'

var suffix = uniqueString(resourceGroup().id)
var names = {
  acr: '${prefix}acr${suffix}'
  env: '${prefix}-env'
  app: '${prefix}-api'
  kv: '${prefix}-kv-${take(suffix, 6)}'
  pg: '${prefix}-pg-${suffix}'
  aoai: '${prefix}-aoai-${suffix}'
  search: '${prefix}-search-${suffix}'
  appIdentity: '${prefix}-app-id'
  githubIdentity: '${prefix}-github-id'
}
var pgDatabase = 'financial_advisor_db'
var pgAdmin = 'advisoradmin'

var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  kvSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  containerAppsContributor: '358470bc-b998-42bd-ab17-a7e34c199c0f'
  reader: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
}

// ---------------------------------------------------------------------------
// Identities
// ---------------------------------------------------------------------------

resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: names.appIdentity
  location: location
}

resource githubIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: names.githubIdentity
  location: location
}

// GitHub Actions exchanges its OIDC token for this identity; no client secret exists
resource githubFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: githubIdentity
  name: 'github-${githubBranch}'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepo}:ref:refs/heads/${githubBranch}'
    audiences: ['api://AzureADTokenExchange']
  }
}

// ---------------------------------------------------------------------------
// Container registry
// ---------------------------------------------------------------------------

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: names.acr
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

resource acrPullForApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, appIdentity.id, roles.acrPull)
  properties: {
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

resource acrPushForGithub 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, githubIdentity.id, roles.acrPush)
  properties: {
    principalId: githubIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPush)
  }
}

// ---------------------------------------------------------------------------
// Postgres (pgvector)
// ---------------------------------------------------------------------------

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: names.pg
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: pgAdmin
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32 }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
  }
}

// pgvector must be allow-listed before CREATE EXTENSION works
resource pgExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: {
    value: 'VECTOR'
    source: 'user-override'
  }
}

resource pgDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: pgDatabase
  dependsOn: [pgExtensions]
}

// 0.0.0.0 - 0.0.0.0 is Azure's "allow Azure services" rule (Container Apps egress)
resource pgAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'allow-azure-services'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
  dependsOn: [pgDb]
}

resource pgAllowOperator 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = if (!empty(operatorIpAddress)) {
  parent: postgres
  name: 'allow-operator'
  properties: {
    startIpAddress: operatorIpAddress
    endIpAddress: operatorIpAddress
  }
  dependsOn: [pgAllowAzure]
}

// ---------------------------------------------------------------------------
// Key Vault
// ---------------------------------------------------------------------------

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: names.kv
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource secretJwt 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'SECRET-KEY'
  properties: { value: jwtSecret }
}

resource secretDatabaseUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'DATABASE-URL'
  properties: {
    value: 'postgresql+asyncpg://${pgAdmin}:${uriComponent(postgresAdminPassword)}@${postgres.properties.fullyQualifiedDomainName}:5432/${pgDatabase}?ssl=require'
  }
}

resource kvSecretsUserForApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, appIdentity.id, roles.kvSecretsUser)
  properties: {
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsUser)
  }
}

resource kvSecretsOfficerForOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(operatorPrincipalId)) {
  scope: keyVault
  name: guid(keyVault.id, operatorPrincipalId, roles.kvSecretsOfficer)
  properties: {
    principalId: operatorPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsOfficer)
  }
}

// ---------------------------------------------------------------------------
// Azure OpenAI
// ---------------------------------------------------------------------------

resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: names.aoai
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: names.aoai // required for Entra ID auth
    disableLocalAuth: true // no API keys at all
    publicNetworkAccess: 'Enabled'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: 'gpt-4o-mini'
  sku: {
    name: chatSkuName
    capacity: chatCapacityK
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o-mini'
      version: '2024-07-18'
    }
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: 'text-embedding-3-small'
  sku: {
    name: embeddingSkuName
    capacity: embeddingCapacityK
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
      version: '1'
    }
  }
  dependsOn: [chatDeployment] // deployments on one account must not run in parallel
}

resource openAiUserForApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openAi
  name: guid(openAi.id, appIdentity.id, roles.openAiUser)
  properties: {
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openAiUser)
  }
}

resource openAiUserForOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(operatorPrincipalId)) {
  scope: openAi
  name: guid(openAi.id, operatorPrincipalId, roles.openAiUser)
  properties: {
    principalId: operatorPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openAiUser)
  }
}

// ---------------------------------------------------------------------------
// Azure AI Search (Free: 50 MB, 3 indexes, one per subscription)
// ---------------------------------------------------------------------------

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: names.search
  location: location
  sku: { name: 'free' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    disableLocalAuth: true // Entra ID only, no admin/query keys
    publicNetworkAccess: 'enabled'
  }
}

resource searchDataForApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, appIdentity.id, roles.searchIndexDataContributor)
  properties: {
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
  }
}

// The app upserts documents; creating the index is done once by the operator (eval ingest)
resource searchDataForOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(operatorPrincipalId)) {
  scope: search
  name: guid(search.id, operatorPrincipalId, roles.searchIndexDataContributor)
  properties: {
    principalId: operatorPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
  }
}

resource searchServiceForOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(operatorPrincipalId)) {
  scope: search
  name: guid(search.id, operatorPrincipalId, roles.searchServiceContributor)
  properties: {
    principalId: operatorPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
  }
}

// ---------------------------------------------------------------------------
// Container Apps
// ---------------------------------------------------------------------------

// No Log Analytics workspace: avoids ingestion charges. Use
// `az containerapp logs show --follow` for live console logs.
resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: names.env
  location: location
  properties: {
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: names.app
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${appIdentity.id}': {} }
  }
  properties: {
    environmentId: containerEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: {
        external: true
        targetPort: apiTargetPort
        transport: 'auto'
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: appIdentity.id
        }
      ]
      // Container Apps reads these from Key Vault with the app identity
      secrets: [
        {
          name: 'secret-key'
          keyVaultUrl: secretJwt.properties.secretUri
          identity: appIdentity.id
        }
        {
          name: 'database-url'
          keyVaultUrl: secretDatabaseUrl.properties.secretUri
          identity: appIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: {
            cpu: json('2.0')
            memory: '4Gi' // NLI + spaCy models need ~2.5 GB
          }
          env: [
            { name: 'SECRET_KEY', secretRef: 'secret-key' }
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'FASTAPI_ENV', value: 'production' }
            { name: 'MODEL_PROVIDER', value: 'azure_openai' }
            { name: 'AZURE_OPENAI_ENDPOINT', value: openAi.properties.endpoint }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chatDeployment.name }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: embeddingDeployment.name }
            { name: 'RETRIEVAL_BACKEND', value: retrievalBackend }
            { name: 'AZURE_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
            { name: 'AZURE_SEARCH_INDEX', value: 'financial-chunks' }
            // Tells DefaultAzureCredential which user-assigned identity to use
            { name: 'AZURE_CLIENT_ID', value: appIdentity.properties.clientId }
          ]
        }
      ]
      scale: {
        minReplicas: 0 // scale to zero when idle
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    acrPullForApp
    kvSecretsUserForApp
  ]
}

resource appContributorForGithub 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: api
  name: guid(api.id, githubIdentity.id, roles.containerAppsContributor)
  properties: {
    principalId: githubIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.containerAppsContributor)
  }
}

// azure/login needs to see the subscription; Reader on this group is enough
resource rgReaderForGithub 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, githubIdentity.id, roles.reader)
  properties: {
    principalId: githubIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.reader)
  }
}

// ---------------------------------------------------------------------------
// Outputs (ids and URLs only; no secrets)
// ---------------------------------------------------------------------------

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output containerAppName string = api.name
output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output keyVaultName string = keyVault.name
output postgresHost string = postgres.properties.fullyQualifiedDomainName
output openAiEndpoint string = openAi.properties.endpoint
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output githubClientId string = githubIdentity.properties.clientId
output tenantId string = subscription().tenantId
output subscriptionId string = subscription().subscriptionId
