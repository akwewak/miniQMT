/// <reference types="vitest" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const RELEASE_VERSION_PLACEHOLDER = '%MINIQMT_RELEASE_VERSION%'

function getReleaseVersion() {
  const versionPath = fileURLToPath(new URL('../release_version.json', import.meta.url))
  const versionInfo = JSON.parse(readFileSync(versionPath, 'utf-8')) as { releaseVersion?: string }
  return versionInfo.releaseVersion || 'unknown'
}

const releaseVersion = getReleaseVersion()

export default defineConfig({
  plugins: [
    {
      name: 'miniqmt-release-version',
      transformIndexHtml(html) {
        return html.split(RELEASE_VERSION_PLACEHOLDER).join(releaseVersion)
      },
    },
    vue(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'icon-192.png', 'icon-512.png'],
      manifest: {
        name: 'miniQMT 持仓监控',
        short_name: 'miniQMT',
        description: 'miniQMT 量化交易系统只读监控界面',
        theme_color: '#1e40af',
        background_color: '#f1f5f9',
        display: 'standalone',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        runtimeCaching: [
          {
            urlPattern: /^https?:\/\/.*\/api\/.*/i,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              expiration: { maxEntries: 50, maxAgeSeconds: 60 },
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
})
