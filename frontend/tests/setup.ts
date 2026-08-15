import { webcrypto } from 'node:crypto'
import { config, enableAutoUnmount } from '@vue/test-utils'
import { Quasar, Notify } from 'quasar'
// A real QDrawer measures QLayout's container width to decide mobile-vs-desktop behavior, which
// is always 0 in happy-dom (no real layout engine) — that makes it always think it's mobile
// regardless of the viewport tests otherwise emulate. Worse, since AppLayout.vue's drawer now
// genuinely opens on mount (see CR "menú plegable"), QDrawer schedules a real 155ms setTimeout for
// its show animation ($layout.animate() in quasar's internals) that fires after Vitest tears down
// `document`, crashing as an unhandled "document is not defined" error in whichever test happened
// to be running when it fires. Every page wraps itself in <AppLayout>, so this stub applies
// globally; AppLayout.spec.ts overrides it locally with a `modelValue`-aware version to actually
// exercise the fold/unfold behavior.
config.global.stubs = { QDrawer: { template: '<div><slot /></div>' } }
// Several components/pages start setInterval-driven polling (useAutoRefresh) on mount; without
// this, a wrapper left mounted at the end of a test leaks a live interval into later tests.
enableAutoUnmount(afterEach)
Object.defineProperty(globalThis, 'crypto', {
  value: {
    randomUUID: () => 'test-request-id',
    getRandomValues: webcrypto.getRandomValues.bind(webcrypto),
    subtle: webcrypto.subtle,
  },
  configurable: true,
})
// Node 22+'s built-in globalThis.localStorage (gated behind --localstorage-file, which the test
// runner doesn't set) shadows happy-dom's own Storage implementation with a non-functional stub —
// every method is undefined. AppLayout.vue persists the dark-mode choice via bare `localStorage`,
// so replace it with a minimal in-memory Storage for the test environment.
class MemoryStorage implements Storage {
  private store = new Map<string, string>()
  get length(): number {
    return this.store.size
  }
  clear(): void {
    this.store.clear()
  }
  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null
  }
  removeItem(key: string): void {
    this.store.delete(key)
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value))
  }
}
const memoryStorage = new MemoryStorage()
for (const target of new Set([globalThis, globalThis.window])) {
  Object.defineProperty(target, 'localStorage', { value: memoryStorage, configurable: true })
}
// @/i18n reads localStorage/navigator at module-load time to pick its initial locale, so it must
// only be imported (dynamically, here) after the localStorage polyfill above is in place — a
// static top-level `import` would be hoisted before it and crash on Node's broken localStorage
// stub. Non-component code (Pinia stores, api/client.ts, api/oidc.ts) calls i18n.global.t()
// directly on this exact singleton, so tests must configure it, not a separate instance.
const { i18n } = await import('@/i18n')
i18n.global.locale.value = 'es-ES'
config.global.plugins = [[Quasar, { plugins: { Notify } }], i18n]
beforeEach(() => {
  i18n.global.locale.value = 'es-ES'
})
