import { fileURLToPath, URL } from 'node:url'
import { quasar, transformAssetUrls } from '@quasar/vite-plugin'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue({ template: { transformAssetUrls } }), quasar()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: {
    environment: 'happy-dom',
    exclude: ['tests/e2e/**', 'node_modules/**'],
    setupFiles: ['./tests/setup.ts'],
    globals: true,
    css: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      thresholds: { lines: 80, functions: 80, branches: 75, statements: 80 },
      include: ['src/**'],
      exclude: [
        // Auto-generated from a live API's OpenAPI schema (npm run generate:openapi) — never hand
        // edited, so tests would only assert generator behaviour, not application logic.
        'src/api/openapi.generated.ts',
        // Pure TypeScript interfaces, no runtime behaviour to exercise.
        'src/api/types.ts',
        // Thin bootstrap entry point: wires plugins and calls mount(); no branching logic.
        'src/main.ts',
        // Single-line <RouterView /> passthrough with no logic.
        'src/App.vue',
      ],
    },
  },
})
