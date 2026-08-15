import { createI18n } from 'vue-i18n'
import { messages } from './locales'

export const SUPPORTED_LOCALES = [
  'es-ES',
  'en-US',
  'ca-ES',
  'gl-ES',
  'fr-FR',
  'pt-PT',
  'de-DE',
  'it-IT',
] as const

export type Locale = (typeof SUPPORTED_LOCALES)[number]

/** Applies whenever the stored/browser-detected locale isn't one we ship (config.md decision). */
export const FALLBACK_LOCALE: Locale = 'en-US'

export const LOCALE_LABELS: Record<Locale, string> = {
  'es-ES': 'Español (España)',
  'en-US': 'English (United States)',
  'ca-ES': 'Català (Espanya)',
  'gl-ES': 'Galego (España)',
  'fr-FR': 'Français (France)',
  'pt-PT': 'Português (Portugal)',
  'de-DE': 'Deutsch (Deutschland)',
  'it-IT': 'Italiano (Italia)',
}

const LOCALE_STORAGE_KEY = 'capataz.locale'

function isSupportedLocale(value: string | null | undefined): value is Locale {
  return !!value && (SUPPORTED_LOCALES as readonly string[]).includes(value)
}

/**
 * Best-effort match of the browser's preferred languages against our supported locale list:
 * an exact code match first (e.g. "fr-FR"), then a same-language match (e.g. browser "fr-CA"
 * matches our "fr-FR"), falling back to FALLBACK_LOCALE if neither pass finds anything.
 */
export function detectBrowserLocale(
  candidates: readonly string[] = navigator.languages ?? [navigator.language],
): Locale {
  const normalized = candidates.map((candidate) => candidate.toLowerCase())
  const exact = SUPPORTED_LOCALES.find((locale) => normalized.includes(locale.toLowerCase()))
  if (exact) return exact
  const languageOnly = normalized.map((candidate) => candidate.split('-')[0] ?? candidate)
  const partial = SUPPORTED_LOCALES.find((locale) =>
    languageOnly.includes((locale.split('-')[0] ?? locale).toLowerCase()),
  )
  return partial ?? FALLBACK_LOCALE
}

export function readStoredLocale(): Locale | undefined {
  const stored = localStorage.getItem(LOCALE_STORAGE_KEY)
  return isSupportedLocale(stored) ? stored : undefined
}

export function persistLocale(locale: Locale): void {
  localStorage.setItem(LOCALE_STORAGE_KEY, locale)
}

export const initialLocale: Locale = readStoredLocale() ?? detectBrowserLocale()

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale,
  fallbackLocale: FALLBACK_LOCALE,
  messages,
})
