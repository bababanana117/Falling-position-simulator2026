/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages は独自ドメイン (https://cusf2026.ddd3h.com) のルートで配信する。
// プロジェクトサイト配下で配信するときは CI で GHPAGES_BASE を設定する。ローカル開発は '/'。
export default defineConfig({
  plugins: [react()],
  base: process.env.GHPAGES_BASE ?? '/',
  test: {
    environment: 'node',
  },
})
