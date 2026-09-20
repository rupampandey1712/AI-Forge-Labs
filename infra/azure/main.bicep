// AI Forge Labs on Azure Container Apps.
//
// WHY CONTAINER APPS rather than AKS: this is one web app, one API and one
// sandbox. AKS gives you a cluster to operate, a control plane to upgrade and a
// networking model to learn, in exchange for scheduling flexibility nothing
// here needs. Container Apps gives scale-to-zero, revisions, managed ingress
// and a Dapr/KEDA escape hatch if the shape ever changes. Choosing the smaller
// thing is the same argument ADR-001 makes about the monolith.
//
// THE DEPLOYMENT SHAPE, and why the sandbox is separate:
//
//   Internet ──> [frontend] ──> [api] ──internal──> [sandbox]
//                                │
//                                ├──> Postgres Flexible Server (private)
//                                ├──> Redis (private)
//                                └──> Key Vault (managed identity)
//
// The sandbox has `external: false` ingress, so it is unreachable from the
// internet and only the API can call it. It has no database connection, no Key
// Vault access and no secrets — because it executes hostile code by design, and
// the only defence that means anything is that there is nothing there to take.
//
// Everything is parameterised so the whole stack can stand up in a throwaway
// resource group and be deleted with one command. An environment you are afraid
// to delete is an environment you will never rebuild correctly.

targetScope = 'resourceGroup'

@description('Short name used as the prefix for every resource. Lowercase alphanumeric.')
@minLength(3)
@maxLength(12)
param appName string = 'aiforge'

@description('Azure region. Defaults to the resource group\'s region.')
param location string = resourceGroup().location

@description('Environment discriminator. Appears in resource names and in the API\'s /health.')
@allowed(['dev', 'staging', 'prod'])
param environmentName string = 'dev'

@description('Postgres administrator login.')
param postgresAdminUser string = 'forgeadmin'

@description('Postgres administrator password. Supply from a pipeline secret; never commit it.')
@secure()
param postgresAdminPassword string

@description('JWT signing secret for the API. 32+ random bytes.')
@secure()
param jwtSecret string

@description('Shared secret the API uses to authenticate to the sandbox.')
@secure()
param sandboxToken string

@description('Optional LLM API key. Empty leaves the game on its deterministic offline provider.')
@secure()
param llmApiKey string = ''

@description('LLM provider: mock, gemini, anthropic or openai.')
@allowed(['mock', 'gemini', 'anthropic', 'openai'])
param llmProvider string = 'mock'

@description('Container image tag to deploy. Use the git SHA, never "latest".')
param imageTag string = 'latest'

@description('Minimum API replicas. 0 enables scale-to-zero, at the cost of a cold start.')
@minValue(0)
param apiMinReplicas int = 1

@description('Minimum sandbox replicas.')
@minValue(0)
param sandboxMinReplicas int = 1

// Deterministic, globally-unique-enough suffix. `uniqueString` on the resource
// group id gives the same answer for repeat deployments to the same group,
// which is what makes this template idempotent.
var suffix = uniqueString(resourceGroup().id)
var prefix = '${appName}-${environmentName}'
var tags = {
  application: 'ai-forge-labs'
  environment: environmentName
  managedBy: 'bicep'
}

// ── Container registry ───────────────────────────────────────────────────────
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: '${appName}acr${suffix}'
  location: location
  tags: tags
  sku: {
    // Basic is enough for three images. Premium buys geo-replication and
    // private endpoints, neither of which this deployment needs yet.
    name: 'Basic'
  }
  properties: {
    // Managed identity is used for pulls, so the admin user stays off.
    adminUserEnabled: false
  }
}

// ── Identity ────────────────────────────────────────────────────────────────
// A user-assigned identity rather than system-assigned, because the same
// identity must be granted registry and Key Vault access *before* the container
// apps exist. A system-assigned identity does not exist until its app does,
// which makes the role assignments a chicken-and-egg problem.
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-identity'
  location: location
  tags: tags
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalType: 'ServicePrincipal'
  }
}

// ── Key Vault ───────────────────────────────────────────────────────────────
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${appName}kv${suffix}'
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    // RBAC rather than access policies: policies are per-vault ACLs that do not
    // show up in any subscription-wide access review, which is how stale grants
    // survive for years.
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

var kvSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource kvAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, identity.id, kvSecretsUserRoleId)
  scope: keyVault
  properties: {
    principalId: identity.properties.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRoleId)
    principalType: 'ServicePrincipal'
  }
}

// Secrets live in the vault, not in the container app definition.
//
// WHY THIS RATHER THAN INLINE `value:` SECRETS: an inline secret is part of the
// container app resource, so anyone with reader access on the app can retrieve
// it, and rotating it means redeploying the app. A vault-backed secret is
// fetched at runtime with the managed identity: rotation is a vault write, and
// the app definition contains a URL rather than a credential.
//
// Until this was wired up the vault was decorative — created, granted a role,
// and referenced by nothing. Infrastructure that exists without being used is
// worse than absent, because it reads as a control that is in place.
var secretValues = {
  'postgres-admin-password': postgresAdminPassword
  'jwt-secret': jwtSecret
  'sandbox-token': sandboxToken
  'llm-api-key': empty(llmApiKey) ? 'unset' : llmApiKey
}

resource vaultSecrets 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = [
  for name in items(secretValues): {
    parent: keyVault
    name: name.key
    properties: {
      value: name.value
      contentType: 'text/plain'
    }
  }
]

// ── Postgres ────────────────────────────────────────────────────────────────
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: '${prefix}-pg-${suffix}'
  location: location
  tags: tags
  sku: {
    // Burstable is right for a single-player learning game: the load is spiky
    // and low, and B1ms costs roughly a tenth of the smallest General Purpose
    // tier. Move to GP when sustained CPU justifies it, not before.
    name: environmentName == 'prod' ? 'Standard_B2s' : 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: 32
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: environmentName == 'prod' ? 14 : 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      // Zone-redundant HA doubles the cost. For a learning game the backup
      // retention above is the right level of durability; this is the line to
      // change if that stops being true.
      mode: 'Disabled'
    }
    authConfig: {
      // Both enabled: password auth for the app's connection string, Entra ID
      // so a human can connect without one being shared around.
      passwordAuth: 'Enabled'
      activeDirectoryAuth: 'Enabled'
      tenantId: subscription().tenantId
    }
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: postgres
  name: 'aiforge'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Container Apps egress IPs are not fixed, so the alternative to this rule is a
// VNet-integrated environment with a private endpoint. That is the correct
// production answer and is left as the documented upgrade path in
// docs/DEPLOYMENT.md rather than being half-built here.
resource allowAzureServices 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ── Redis ───────────────────────────────────────────────────────────────────
resource redis 'Microsoft.Cache/redis@2023-08-01' = {
  name: '${prefix}-redis-${suffix}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'Basic'
      family: 'C'
      capacity: 0
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    redisConfiguration: {
      // Cache only — everything in Redis is rebuildable from Postgres, so
      // eviction under pressure is correct behaviour rather than data loss.
      'maxmemory-policy': 'allkeys-lru'
    }
  }
}

// These two are composed from keys that only exist once the resources do, so
// they cannot be passed in as parameters — but they are still credentials and
// belong in the vault rather than in the app definition.
resource databaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'database-url'
  properties: {
    value: 'postgresql+asyncpg://${postgresAdminUser}:${postgresAdminPassword}@${postgres.properties.fullyQualifiedDomainName}:5432/aiforge?ssl=require'
  }
}

resource redisUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'redis-url'
  properties: {
    value: 'rediss://:${redis.listKeys().primaryKey}@${redis.properties.hostName}:6380/0'
  }
}

// ── Observability ───────────────────────────────────────────────────────────
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-insights'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// ── Container Apps environment ──────────────────────────────────────────────
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  tags: tags
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

var registryServer = registry.properties.loginServer

// Common identity/registry block. Bicep has no partial-object spread, so this
// is repeated per app rather than factored — duplication that reads clearly
// beats a module indirection for three apps.
var identityConfig = {
  type: 'UserAssigned'
  userAssignedIdentities: {
    '${identity.id}': {}
  }
}

// ── The sandbox ─────────────────────────────────────────────────────────────
// `external: false` is the security boundary. This app has no public ingress,
// no database, no Key Vault access and one secret — the token it checks. It
// runs hostile code, so the design assumption is that it will eventually be
// compromised, and the blast radius is deliberately a container that could
// already run arbitrary code.
resource sandboxApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-sandbox'
  location: location
  tags: union(tags, { component: 'sandbox', trust: 'untrusted' })
  identity: identityConfig
  dependsOn: [acrPull, kvAccess, vaultSecrets]
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: false
        targetPort: 8001
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: registryServer
          identity: identity.id
        }
      ]
      // The sandbox's only secret. It reads this from the vault with the same
      // identity, which is the *only* vault access it has — and it is granted
      // at the vault level rather than per-secret, which is the one thing about
      // this arrangement worth revisiting if the vault ever holds more.
      secrets: [
        {
          name: 'sandbox-token'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/sandbox-token'
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'sandbox'
          image: '${registryServer}/aiforge-sandbox-service:${imageTag}'
          resources: {
            // Generous relative to the rest of the stack: this container is
            // where the player's O(n^2) solution actually runs, and an OOM here
            // should be the submission's memory limit firing, not the pod's.
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            { name: 'SANDBOX_MODE', value: 'subprocess' }
            { name: 'SANDBOX_SERVICE_TOKEN', secretRef: 'sandbox-token' }
            { name: 'SANDBOX_TIMEOUT_CEILING', value: '30' }
            { name: 'SANDBOX_MEMORY_CEILING_MB', value: '1024' }
            { name: 'SANDBOX_MAX_REQUEST_BYTES', value: '262144' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8001 }
              initialDelaySeconds: 5
              periodSeconds: 20
            }
          ]
        }
      ]
      scale: {
        minReplicas: sandboxMinReplicas
        maxReplicas: 10
        rules: [
          {
            name: 'concurrent-executions'
            http: {
              metadata: {
                // Low on purpose. Each execution is a subprocess with a CPU and
                // memory budget; packing many onto one replica means they
                // contend and every player's timing measurement becomes noise.
                // The benchmark challenges depend on this being honest.
                concurrentRequests: '4'
              }
            }
          }
        ]
      }
    }
  }
}

// ── The API ─────────────────────────────────────────────────────────────────
resource apiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-api'
  location: location
  tags: union(tags, { component: 'api', trust: 'trusted' })
  identity: identityConfig
  dependsOn: [acrPull, kvAccess, database, vaultSecrets]
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
        corsPolicy: {
          allowedOrigins: ['https://${prefix}-web.${environment.properties.defaultDomain}']
          allowedMethods: ['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS']
          allowedHeaders: ['*']
          allowCredentials: true
        }
      }
      registries: [
        {
          server: registryServer
          identity: identity.id
        }
      ]
      // `keyVaultUrl` + `identity` means the platform fetches the value with the
      // managed identity at start-up. The app definition holds a URL; the
      // credential never appears in it, in the deployment history, or in
      // `az containerapp show`.
      secrets: [
        {
          name: 'database-url'
          keyVaultUrl: databaseUrlSecret.properties.secretUri
          identity: identity.id
        }
        {
          name: 'redis-url'
          keyVaultUrl: redisUrlSecret.properties.secretUri
          identity: identity.id
        }
        {
          name: 'jwt-secret'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/jwt-secret'
          identity: identity.id
        }
        {
          name: 'sandbox-token'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/sandbox-token'
          identity: identity.id
        }
        {
          name: 'llm-api-key'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/llm-api-key'
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: '${registryServer}/aiforge-api:${imageTag}'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'ENVIRONMENT', value: environmentName }
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'REDIS_URL', secretRef: 'redis-url' }
            { name: 'JWT_SECRET', secretRef: 'jwt-secret' }
            // The API never executes code. `remote` is what enforces that at
            // runtime: with this set, build_backend refuses to fall back to a
            // local subprocess even if SANDBOX_SERVICE_URL is missing.
            { name: 'SANDBOX_MODE', value: 'remote' }
            { name: 'SANDBOX_SERVICE_URL', value: 'https://${sandboxApp.properties.configuration.ingress.fqdn}' }
            { name: 'SANDBOX_SERVICE_TOKEN', secretRef: 'sandbox-token' }
            { name: 'LLM_PROVIDER', value: llmProvider }
            { name: 'LLM_API_KEY', secretRef: 'llm-api-key' }
            // No AZURE_KEY_VAULT_URI or AZURE_CLIENT_ID: the application does not
            // talk to Key Vault itself. The platform resolves the secrets above
            // before the container starts, so the app only ever sees plain env
            // vars. Passing vault config it never reads would be cargo cult.
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
          ]
          probes: [
            {
              // Liveness on /health/live only: a readiness-style check here
              // would restart the container whenever the database blips, which
              // turns a brief dependency outage into a restart loop.
              type: 'Liveness'
              httpGet: { path: '/api/v1/health/live', port: 8000 }
              initialDelaySeconds: 10
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: '/api/v1/health/ready', port: 8000 }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: apiMinReplicas
        maxReplicas: 5
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: { concurrentRequests: '40' }
            }
          }
        ]
      }
    }
  }
}

// ── The frontend ────────────────────────────────────────────────────────────
resource webApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-web'
  location: location
  tags: union(tags, { component: 'web' })
  identity: identityConfig
  dependsOn: [acrPull]
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: registryServer
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: '${registryServer}/aiforge-web:${imageTag}'
          resources: {
            // Static assets behind nginx. This is as small as Container Apps
            // allows and it is still overprovisioned.
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            { name: 'API_UPSTREAM', value: 'https://${apiApp.properties.configuration.ingress.fqdn}' }
          ]
        }
      ]
      scale: {
        // Scale-to-zero is fine here: the cold start is nginx, which is
        // milliseconds, unlike the API where it would be a Python import tree.
        minReplicas: 0
        maxReplicas: 3
      }
    }
  }
}

// ── Outputs ─────────────────────────────────────────────────────────────────
output webUrl string = 'https://${webApp.properties.configuration.ingress.fqdn}'
output apiUrl string = 'https://${apiApp.properties.configuration.ingress.fqdn}'
@description('Internal only — not reachable from the internet. Shown to confirm the boundary.')
output sandboxInternalUrl string = 'https://${sandboxApp.properties.configuration.ingress.fqdn}'
output registryLoginServer string = registryServer
output keyVaultUri string = keyVault.properties.vaultUri
output postgresFqdn string = postgres.properties.fullyQualifiedDomainName
