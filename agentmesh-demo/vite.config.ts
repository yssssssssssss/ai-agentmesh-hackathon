import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// 后端(uvicorn)默认 8010;同源代理使 httponly+samesite=lax 会话 cookie 生效。

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const apiTarget = env.AGENTMESH_API_TARGET || 'http://127.0.0.1:8010'

  return {
    plugins: [react()],
    server: {
      port: 5178,
      host: true,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
