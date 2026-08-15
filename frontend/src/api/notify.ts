import { Notify } from 'quasar'
import { ApiError } from './client'

/**
 * Shows a negative Notify from a caught mutation error (CR-094): the real backend detail when
 * available — any `ApiError` except 401/403, which already carry a fixed friendly message from
 * client.ts — falls back to `fallback` otherwise (non-`ApiError`, or 401/403).
 */
export function notifyApiError(error: unknown, fallback: string): void {
  const message =
    error instanceof ApiError && error.status !== 401 && error.status !== 403 ? error.message : fallback
  Notify.create({ type: 'negative', message })
}
