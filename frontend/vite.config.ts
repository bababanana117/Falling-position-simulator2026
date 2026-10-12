/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 本番は Cloudflare Workers の静的配信 (https://cusf2026.ddd3h.com) でルート配下。
// サブパス配下で配信するときだけ GHPAGES_BASE を設定する。ローカル開発は '/'。
export default defineConfig({
  plugins: [react()],
  base: process.env.GHPAGES_BASE ?? '/',
  test: {
    environment: 'node',
  },
})
