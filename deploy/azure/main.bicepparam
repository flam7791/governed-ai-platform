// Parameters for main.bicep. Secrets are read from the environment, never stored here:
//
//   python scripts/new_env.py --azure            # writes deploy/azure/secrets.env (git-ignored)
//   set -a; . deploy/azure/secrets.env; set +a
//   az deployment group create -g <resource group> -f deploy/azure/main.bicep \
//       -p deploy/azure/main.bicepparam -p azureOpenAiEndpoint=https://<name>.openai.azure.com
using 'main.bicep'

param prefix = 'govai'
param azureOpenAiEndpoint = readEnvironmentVariable('AZURE_OPENAI_ENDPOINT', 'https://example.openai.azure.com')
param azureOpenAiAccountName = readEnvironmentVariable('AZURE_OPENAI_ACCOUNT', '')
param enableCopilotStudio = false
param approvalsAllowedCidrs = []

param llmgwKeyAgents = readEnvironmentVariable('LLMGW_KEY_AGENTS')
param llmgwKeyEvidence = readEnvironmentVariable('LLMGW_KEY_EVIDENCE')
param llmgwKeyResearch = readEnvironmentVariable('LLMGW_KEY_RESEARCH')
param gatewayMetricsToken = readEnvironmentVariable('GATEWAY_METRICS_TOKEN')
param agentsMetricsToken = readEnvironmentVariable('AGENTS_METRICS_TOKEN')
param govagentsApiTokens = readEnvironmentVariable('GOVAGENTS_API_TOKENS')
param evidenceMcpTokenAgents = readEnvironmentVariable('EVIDENCE_MCP_TOKEN_AGENTS')
param evidenceMcpTokensJson = readEnvironmentVariable('EVIDENCE_MCP_TOKENS_JSON')
