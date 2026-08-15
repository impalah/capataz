import { useAuthStore } from '@/stores/auth'
import { getAccessToken } from '@/api/oidc'
import { i18n } from '@/i18n'
import { runtimeConfig } from '@/api/runtimeConfig'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly requestId?: string,
  ) {
    super(message)
  }
}
const baseUrl = runtimeConfig.apiBaseUrl
const requestId = () => crypto.randomUUID()

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore()
  const headers = new Headers(init.headers)
  const id = requestId()
  headers.set('Accept', 'application/json')
  headers.set('X-Request-ID', id)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (auth.devMockEnabled) {
    headers.set('X-Dev-User', auth.subject)
    headers.set('X-Dev-Groups', auth.groups.join(','))
  } else {
    const token = await getAccessToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers })
  if (response.status === 401) {
    auth.markUnauthorized()
    throw new ApiError(
      401,
      i18n.global.t('errors.sessionExpired'),
      response.headers.get('X-Request-ID') ?? id,
    )
  }
  if (response.status === 403)
    throw new ApiError(403, i18n.global.t('errors.forbidden'), response.headers.get('X-Request-ID') ?? id)
  if (!response.ok) {
    const problem = (await response.json().catch(() => ({ detail: i18n.global.t('errors.generic') }))) as {
      detail?: string
    }
    throw new ApiError(
      response.status,
      problem.detail ?? i18n.global.t('errors.generic'),
      response.headers.get('X-Request-ID') ?? id,
    )
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
