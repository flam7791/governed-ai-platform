// governed-ai-platform on Azure Container Apps.
//
// One resource group: Log Analytics, a virtual network, a Container Apps environment inside it,
// a user-assigned managed identity, Key Vault holding every secret, Azure Files for the two
// SQLite stores, and the three services:
//
//   agents        external ingress (the approvals page), optionally limited to given CIDRs
//   gateway       internal ingress only; calls Azure OpenAI with the managed identity (no key)
//   evidence-mcp  internal ingress only; bearer token from the agents service
//   evidence-m365 optional, external ingress with Entra ID tokens, for Copilot Studio
//
// Secrets are written to Key Vault by this deployment (from @secure() parameters, read from the
// environment by main.bicepparam) and reach the containers as Key Vault references through the
// managed identity: never as plain values in the Container Apps configuration.
//
// Compiled and linted in CI; not deployed from this repository (no subscription). See
// docs/azure.md.

targetScope = 'resourceGroup'

@description('Azure region.')
param location string = resourceGroup().location

@description('Short prefix for resource names (lowercase letters and digits).')
@maxLength(10)
param prefix string = 'govai'

@description('Image tags of the components (GitHub Container Registry).')
param gatewayImage string = 'ghcr.io/flam7791/governed-llm-gateway:0.3.0'
param evidenceImage string = 'ghcr.io/flam7791/policy-evidence-mcp:0.3.1'
param agentsImage string = 'ghcr.io/flam7791/governed-agents:0.3.1'

@description('Azure OpenAI endpoint, e.g. https://my-aoai.openai.azure.com (no trailing slash).')
param azureOpenAiEndpoint string

@description('Name of the Azure OpenAI account in this resource group, to grant the gateway access. Empty: grant it yourself.')
param azureOpenAiAccountName string = ''

@description('Azure OpenAI deployment names.')
param fastDeployment string = 'gpt-4.1-mini'
param strongDeployment string = 'gpt-4.1'
param embeddingDeployment string = 'text-embedding-3-small'

@description('CIDR ranges allowed to reach the approvals page. Empty: no IP restriction (put Entra ID authentication in front).')
param approvalsAllowedCidrs array = []

@description('Also expose the evidence server to Copilot Studio, with Entra ID tokens.')
param enableCopilotStudio bool = false
param entraTenantId string = tenant().tenantId
param evidenceAudience string = 'api://policy-evidence'

@description('OTLP endpoint for traces (an OpenTelemetry Collector). Empty: tracing off.')
param otlpEndpoint string = ''

@secure()
param llmgwKeyAgents string
@secure()
param llmgwKeyEvidence string
@secure()
param llmgwKeyResearch string
@secure()
param gatewayMetricsToken string
@secure()
param agentsMetricsToken string
@secure()
@description('People and roles for the approvals page: name:role:token,...')
param govagentsApiTokens string
@secure()
@description('The agents service token for the evidence server.')
param evidenceMcpTokenAgents string
@secure()
@description('The evidence server token file (JSON, hashes only), from new_env.py --azure.')
param evidenceMcpTokensJson string

var suffix = uniqueString(resourceGroup().id)
var gatewayConfig = replace(
  replace(
    replace(
      replace(loadTextContent('../../config/gateway.azure.json'), '__AZURE_OPENAI_ENDPOINT__', azureOpenAiEndpoint),
      '__FAST_DEPLOYMENT__',
      fastDeployment
    ),
    '__STRONG_DEPLOYMENT__',
    strongDeployment
  ),
  '__EMBEDDING_DEPLOYMENT__',
  embeddingDeployment
)

// ------------------------------------------------------------------ monitoring, network, identity

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs-${suffix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: '${prefix}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.40.0.0/16'] }
    subnets: [
      {
        name: 'apps'
        properties: {
          addressPrefix: '10.40.0.0/23'
          delegations: [
            { name: 'apps', properties: { serviceName: 'Microsoft.App/environments' } }
          ]
        }
      }
    ]
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id'
  location: location
}

// ------------------------------------------------------------------ secrets

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('${prefix}kv${suffix}', 24)
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled' // use a private endpoint in production (docs/azure.md)
  }
}

var secretValues = {
  'llmgw-key-agents': llmgwKeyAgents
  'llmgw-key-evidence': llmgwKeyEvidence
  'llmgw-key-research': llmgwKeyResearch
  'gateway-metrics-token': gatewayMetricsToken
  'agents-metrics-token': agentsMetricsToken
  'govagents-api-tokens': govagentsApiTokens
  'evidence-mcp-token-agents': evidenceMcpTokenAgents
  'evidence-mcp-tokens': evidenceMcpTokensJson
  'gateway-config': gatewayConfig
}

resource secrets 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = [
  for item in items(secretValues): {
    parent: vault
    name: item.key
    properties: { value: item.value }
  }
]

var keyVaultSecretsUser = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4633458b-17de-408a-b874-0445c86b69e6'
)

resource canReadSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, keyVaultSecretsUser)
  scope: vault
  properties: {
    roleDefinitionId: keyVaultSecretsUser
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (!empty(azureOpenAiAccountName)) {
  name: azureOpenAiAccountName
}

var openAiUser = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
)

resource canCallOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(azureOpenAiAccountName)) {
  name: guid(resourceGroup().id, azureOpenAiAccountName, identity.id, openAiUser)
  scope: openAi
  properties: {
    roleDefinitionId: openAiUser
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ------------------------------------------------------------------ storage for SQLite

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take('${prefix}st${suffix}', 24)
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_ZRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource files 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource shares 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = [
  for share in ['gateway-data', 'agents-data']: {
    parent: files
    name: share
    properties: { shareQuota: 5 }
  }
]

// ------------------------------------------------------------------ Container Apps environment

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: vnet.properties.subnets[0].id
      internal: false
    }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
  }
}

resource envStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = [
  for (share, i) in ['gateway-data', 'agents-data']: {
    parent: env
    name: share
    properties: {
      azureFile: {
        accountName: storage.name
        accountKey: storage.listKeys().keys[0].value
        shareName: shares[i].name
        accessMode: 'ReadWrite'
      }
    }
  }
]

// ------------------------------------------------------------------ the services

var kv = vault.properties.vaultUri
func kvSecret(vaultUri string, name string, identityId string) object => {
  name: name
  keyVaultUrl: '${vaultUri}secrets/${name}'
  identity: identityId
}

var identities = {
  userAssigned: { '${identity.id}': {} }
}
var otelEnv = empty(otlpEndpoint) ? [] : [{ name: 'OTEL_EXPORTER_OTLP_ENDPOINT', value: otlpEndpoint }]
// SQLite on Azure Files: byte-range locks off (nobrl), one replica. PostgreSQL for more.
var sqliteMount = 'dir_mode=0777,file_mode=0777,uid=10001,gid=10001,nobrl'

resource gateway 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'gateway'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: identities.userAssigned }
  dependsOn: [canReadSecrets, secrets]
  properties: {
    environmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: false, targetPort: 8080, transport: 'http' }
      secrets: [
        kvSecret(kv, 'llmgw-key-agents', identity.id)
        kvSecret(kv, 'llmgw-key-evidence', identity.id)
        kvSecret(kv, 'llmgw-key-research', identity.id)
        kvSecret(kv, 'gateway-metrics-token', identity.id)
        kvSecret(kv, 'gateway-config', identity.id)
      ]
    }
    template: {
      scale: { minReplicas: 1, maxReplicas: 1 }
      containers: [
        {
          name: 'gateway'
          image: gatewayImage
          args: ['llmgw', 'serve', '--config', '/config/gateway-config', '--host', '0.0.0.0', '--port', '8080']
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(
            [
              { name: 'LLMGW_DB_PATH', value: '/data/gateway.db' }
              { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
              { name: 'LLMGW_KEY_AGENTS', secretRef: 'llmgw-key-agents' }
              { name: 'LLMGW_KEY_EVIDENCE', secretRef: 'llmgw-key-evidence' }
              { name: 'LLMGW_KEY_RESEARCH', secretRef: 'llmgw-key-research' }
              { name: 'LLMGW_METRICS_TOKEN', secretRef: 'gateway-metrics-token' }
            ],
            otelEnv
          )
          probes: [
            { type: 'Readiness', httpGet: { path: '/healthz', port: 8080 }, periodSeconds: 10 }
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8080 }, initialDelaySeconds: 10, periodSeconds: 20 }
          ]
          volumeMounts: [
            { volumeName: 'config', mountPath: '/config' }
            { volumeName: 'data', mountPath: '/data' }
          ]
        }
      ]
      volumes: [
        { name: 'config', storageType: 'Secret', secrets: [{ secretRef: 'gateway-config', path: 'gateway-config' }] }
        { name: 'data', storageType: 'AzureFile', storageName: envStorage[0].name, mountOptions: sqliteMount }
      ]
    }
  }
}

func evidenceArgs(auth string, host string, publicUrl string) array => concat(
  ['evidence-mcp', 'serve', '--transport', 'streamable-http', '--host', '0.0.0.0', '--port', '8000', '--allowed-host', host],
  auth == 'entra'
    ? ['--auth', 'entra', '--public-url', publicUrl]
    : ['--auth', 'tokens', '--tokens-file', '/app/secrets/evidence-mcp-tokens']
)

var evidenceEnv = concat(
  [
    { name: 'EVIDENCE_MCP_MAX_CLASSIFICATION', value: 'internal' }
    { name: 'EVIDENCE_MCP_EMBEDDINGS_URL', value: 'http://gateway/v1' }
    { name: 'EVIDENCE_MCP_EMBEDDINGS_MODEL', value: 'auto' }
    { name: 'EVIDENCE_MCP_EMBEDDINGS_API_KEY', secretRef: 'llmgw-key-evidence' }
    { name: 'EVIDENCE_MCP_CACHE_DIR', value: '/tmp/evidence-cache' }
    { name: 'EVIDENCE_MCP_ENTRA_TENANT_ID', value: entraTenantId }
    { name: 'EVIDENCE_MCP_ENTRA_AUDIENCE', value: evidenceAudience }
  ],
  otelEnv
)
var indexCommand = [
  'sh'
  '-c'
  'for i in 1 2 3 4 5 6; do evidence-mcp ingest --corpus sample_corpus --embeddings && exit 0; sleep 10; done; exec evidence-mcp ingest --corpus sample_corpus'
]

resource evidence 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'evidence-mcp'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: identities.userAssigned }
  dependsOn: [canReadSecrets, secrets]
  properties: {
    environmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: false, targetPort: 8000, transport: 'http' }
      secrets: [
        kvSecret(kv, 'llmgw-key-evidence', identity.id)
        kvSecret(kv, 'evidence-mcp-tokens', identity.id)
      ]
    }
    template: {
      scale: { minReplicas: 1, maxReplicas: 1 } // MCP sessions live in memory
      initContainers: [
        {
          name: 'index'
          image: evidenceImage
          command: indexCommand
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: evidenceEnv
          volumeMounts: [{ volumeName: 'index', mountPath: '/app/index' }]
        }
      ]
      containers: [
        {
          name: 'evidence-mcp'
          image: evidenceImage
          args: evidenceArgs('tokens', 'evidence-mcp', '')
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: evidenceEnv
          probes: [{ type: 'Readiness', tcpSocket: { port: 8000 }, periodSeconds: 10 }]
          volumeMounts: [
            { volumeName: 'index', mountPath: '/app/index' }
            { volumeName: 'tokens', mountPath: '/app/secrets' }
          ]
        }
      ]
      volumes: [
        { name: 'index', storageType: 'EmptyDir' }
        { name: 'tokens', storageType: 'Secret', secrets: [{ secretRef: 'evidence-mcp-tokens', path: 'evidence-mcp-tokens' }] }
      ]
    }
  }
}

// The same server for Copilot Studio: external ingress, every call with a user's Entra ID token.
resource evidenceM365 'Microsoft.App/containerApps@2024-03-01' = if (enableCopilotStudio) {
  name: 'evidence-m365'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: identities.userAssigned }
  dependsOn: [canReadSecrets, secrets]
  properties: {
    environmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: true, targetPort: 8000, transport: 'http', allowInsecure: false }
      secrets: [kvSecret(kv, 'llmgw-key-evidence', identity.id)]
    }
    template: {
      scale: { minReplicas: 1, maxReplicas: 1 }
      initContainers: [
        {
          name: 'index'
          image: evidenceImage
          command: indexCommand
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: evidenceEnv
          volumeMounts: [{ volumeName: 'index', mountPath: '/app/index' }]
        }
      ]
      containers: [
        {
          name: 'evidence-mcp'
          image: evidenceImage
          args: evidenceArgs(
            'entra',
            'evidence-m365.${env.properties.defaultDomain}',
            'https://evidence-m365.${env.properties.defaultDomain}/mcp'
          )
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: evidenceEnv
          probes: [{ type: 'Readiness', tcpSocket: { port: 8000 }, periodSeconds: 10 }]
          volumeMounts: [{ volumeName: 'index', mountPath: '/app/index' }]
        }
      ]
      volumes: [{ name: 'index', storageType: 'EmptyDir' }]
    }
  }
}

resource agents 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'agents'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: identities.userAssigned }
  dependsOn: [canReadSecrets, secrets]
  properties: {
    environmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: {
        external: true
        targetPort: 8090
        transport: 'http'
        allowInsecure: false
        ipSecurityRestrictions: [
          for (cidr, i) in approvalsAllowedCidrs: {
            name: 'allowed-${i}'
            action: 'Allow'
            ipAddressRange: cidr
          }
        ]
      }
      secrets: [
        kvSecret(kv, 'llmgw-key-agents', identity.id)
        kvSecret(kv, 'evidence-mcp-token-agents', identity.id)
        kvSecret(kv, 'govagents-api-tokens', identity.id)
        kvSecret(kv, 'agents-metrics-token', identity.id)
      ]
    }
    template: {
      scale: { minReplicas: 1, maxReplicas: 1 }
      containers: [
        {
          name: 'agents'
          image: agentsImage
          args: ['govagents', 'serve', '--host', '0.0.0.0', '--port', '8090']
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(
            [
              { name: 'GOVAGENTS_PROVIDER', value: 'openai_compatible' }
              { name: 'GOVAGENTS_BASE_URL', value: 'http://gateway/v1' }
              { name: 'GOVAGENTS_MODEL_FAST', value: 'fast' }
              { name: 'GOVAGENTS_MODEL_STRONG', value: 'strong' }
              { name: 'GOVAGENTS_EVIDENCE_MCP_URL', value: 'http://evidence-mcp/mcp' }
              { name: 'GOVAGENTS_API_KEY', secretRef: 'llmgw-key-agents' }
              { name: 'GOVAGENTS_EVIDENCE_MCP_TOKEN', secretRef: 'evidence-mcp-token-agents' }
              { name: 'GOVAGENTS_API_TOKENS', secretRef: 'govagents-api-tokens' }
              { name: 'GOVAGENTS_METRICS_TOKEN', secretRef: 'agents-metrics-token' }
            ],
            otelEnv
          )
          probes: [
            { type: 'Readiness', httpGet: { path: '/healthz', port: 8090 }, periodSeconds: 10 }
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8090 }, initialDelaySeconds: 10, periodSeconds: 20 }
          ]
          volumeMounts: [{ volumeName: 'data', mountPath: '/data' }]
        }
      ]
      volumes: [
        { name: 'data', storageType: 'AzureFile', storageName: envStorage[1].name, mountOptions: sqliteMount }
      ]
    }
  }
}

output approvalsUrl string = 'https://${agents.properties.configuration.ingress.fqdn}'
output copilotStudioMcpUrl string = enableCopilotStudio ? 'https://evidence-m365.${env.properties.defaultDomain}/mcp' : ''
output keyVaultName string = vault.name
output identityClientId string = identity.properties.clientId
