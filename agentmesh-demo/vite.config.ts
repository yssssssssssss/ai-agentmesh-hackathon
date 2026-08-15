import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')

  return {
    plugins: [react()],
    server: {
      port: 5178,
      host: true,
      proxy: {
        '/api': env.AGENTMESH_API_PROXY ?? env.AGENTMESH_API_TARGET ?? 'http://127.0.0.1:8010',
      },
    },
    test: {
      environment: 'node',
      restoreMocks: true,
    },
  }
})
