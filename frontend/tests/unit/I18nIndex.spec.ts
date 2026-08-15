import { detectBrowserLocale, readStoredLocale, persistLocale } from '@/i18n'

describe('i18n locale detection/persistence', () => {
  afterEach(() => {
    localStorage.clear()
  })

  it('matches an exact supported locale code first', () => {
    expect(detectBrowserLocale(['fr-FR'])).toBe('fr-FR')
  })

  it('falls back to a same-language match when the exact region differs', () => {
    expect(detectBrowserLocale(['pt-BR'])).toBe('pt-PT')
  })

  it('is case-insensitive when matching', () => {
    expect(detectBrowserLocale(['DE-de'])).toBe('de-DE')
  })

  it('falls back to en-US when nothing matches, exact or partial', () => {
    expect(detectBrowserLocale(['ja-JP'])).toBe('en-US')
  })

  it('prefers an earlier candidate in the list over a later one', () => {
    expect(detectBrowserLocale(['xx-XX', 'it-IT'])).toBe('it-IT')
  })

  it('readStoredLocale returns undefined when nothing is stored', () => {
    expect(readStoredLocale()).toBeUndefined()
  })

  it('readStoredLocale returns undefined for a stored value outside the supported list', () => {
    localStorage.setItem('capataz.locale', 'xx-XX')
    expect(readStoredLocale()).toBeUndefined()
  })

  it('persistLocale writes to localStorage and readStoredLocale reads it back', () => {
    persistLocale('gl-ES')
    expect(localStorage.getItem('capataz.locale')).toBe('gl-ES')
    expect(readStoredLocale()).toBe('gl-ES')
  })
})
