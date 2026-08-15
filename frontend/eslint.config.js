import js from '@eslint/js'
import prettier from 'eslint-config-prettier'
import vue from 'eslint-plugin-vue'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default [
  {
    ignores: [
      'dist/**',
      'coverage/**',
      'playwright-report/**',
      'test-results/**',
      'public/mockServiceWorker.js',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...vue.configs['flat/recommended'],
  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
      parserOptions: { parser: tseslint.parser, extraFileExtensions: ['.vue'] },
    },
    rules: { '@typescript-eslint/no-explicit-any': 'error', 'vue/multi-word-component-names': 'off' },
  },
  {
    // Runtime config script (see docs/adr/007-runtime-frontend-config.en.md): plain browser script,
    // not part of the Vite/TS module graph, so it only needs the `window` global.
    files: ['public/config.js'],
    languageOptions: { globals: { ...globals.browser } },
  },
  prettier,
]
