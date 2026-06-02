import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const viteApiBase = env.VITE_API_BASE_URL || ''
  const viteAstraedgeApiKey = env.VITE_ASTRAEDGE_API_KEY || ''
  const viteApiKey = env.VITE_API_KEY || ''
  return {
    root: '.',
    define: {
      __VITE_API_BASE_URL__: JSON.stringify(viteApiBase),
    },
    plugins: [
      {
        name: 'astraedge-html-env',
        transformIndexHtml(html) {
          return html
            .replace(/%VITE_API_BASE_URL%/g, viteApiBase)
            .replace(/%VITE_ASTRAEDGE_API_KEY%/g, viteAstraedgeApiKey)
            .replace(/%VITE_API_KEY%/g, viteApiKey)
        },
      },
    ],
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
    },
    preview: {
      host: '127.0.0.1',
      port: 4173,
      strictPort: true,
    },
  }
})
