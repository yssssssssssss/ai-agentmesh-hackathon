import { defineConfig, devices } from '@playwright/test'

const e2eDatabasePath = `/tmp/agentmesh-playwright-${process.pid}-${Date.now()}.sqlite3`

const frontendPort = Number(process.env.AGENTMESH_E2E_FRONTEND_PORT ?? 5181)
const backendPort = Number(process.env.AGENTMESH_E2E_BACKEND_PORT ?? 8021)

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  expect: { timeout: 15_000 },
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `.venv/bin/python -m uvicorn agentmesh.app:app --host 127.0.0.1 --port ${backendPort}`,
      cwd: '..',
      url: `http://127.0.0.1:${backendPort}/api/auth/oauth/status`,
      reuseExistingServer: false,
      env: {
        AGENTMESH_DB_PATH: e2eDatabasePath,
        AGENTMESH_DEMO_MODE: '1',
        AGENTMESH_TASK_MANAGEMENT: 'write',
        AGENTMESH_AGENT_RUNTIME: process.env.AGENTMESH_E2E_AGENT_RUNTIME ?? 'legacy',
        AGENTMESH_AUTOMATION_MODE: process.env.AGENTMESH_E2E_AUTOMATION_MODE ?? 'off',
        AGENTMESH_MEMORY_LEARNING: 'off',
        AGENTMESH_MEMORY_CONTEXT: 'off',
        AGENTMESH_SKIP_DOTENV: '1',
        AGENTMESH_O2_COMMAND: 'agentmesh-o2-disabled-for-tests',
        AGENTMESH_O2_RESEARCH_ENABLED: 'false',
        AGENTMESH_WEB_PROVIDER: '',
        AGENTMESH_DATA_API_URL: '',
        AGENTMESH_DATA_API_KEY: '',
        AI_API_URL: '',
        AI_API_KEY: '',
        AGENTMESH_LLM_BASE_URL: '',
        AGENTMESH_LLM_API_KEY: '',
        AGENTMESH_MODELS: '',
        AGENTMESH_MODEL_PRIMARY_BASE_URL: '',
        AGENTMESH_MODEL_PRIMARY_API_KEY: '',
        AGENTMESH_MODEL_FALLBACK_BASE_URL: '',
        AGENTMESH_MODEL_FALLBACK_API_KEY: '',
        AGENTMESH_TAVILY_API_URL: '',
        AGENTMESH_TAVILY_API_KEY: '',
        AGENTMESH_FIRECRAWL_ENABLED: 'false',
        AGENTMESH_FIRECRAWL_API_KEY: '',
        AGENTMESH_EMBEDDING_ENABLED: 'false',
        AGENTMESH_DOCUMENT_SYNC_THRESHOLD_BYTES: '128',
      },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort}`,
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: false,
      env: { AGENTMESH_API_PROXY: `http://127.0.0.1:${backendPort}` },
    },
  ],
})
