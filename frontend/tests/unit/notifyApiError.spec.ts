import { mount } from '@vue/test-utils'
import { Notify } from 'quasar'
import { notifyApiError } from '@/api/notify'
import { ApiError } from '@/api/client'

describe('notifyApiError', () => {
  beforeEach(() => {
    // Notify.create is only bound once the Quasar plugin has been installed on some app instance
    // (tests/setup.ts registers it globally, but only mount() actually triggers app.use()).
    mount({ template: '<div />' })
  })

  it('uses the real backend detail for a non-401/403 ApiError (CR-094)', () => {
    const spy = vi.spyOn(Notify, 'create')
    notifyApiError(new ApiError(409, 'Version mismatch'), 'fallback')
    expect(spy).toHaveBeenCalledWith({ type: 'negative', message: 'Version mismatch' })
  })

  it('uses the fallback for a 401 ApiError, even though it carries a message', () => {
    const spy = vi.spyOn(Notify, 'create')
    notifyApiError(new ApiError(401, 'Tu sesión ya no es válida.'), 'fallback')
    expect(spy).toHaveBeenCalledWith({ type: 'negative', message: 'fallback' })
  })

  it('uses the fallback for a 403 ApiError, even though it carries a message', () => {
    const spy = vi.spyOn(Notify, 'create')
    notifyApiError(new ApiError(403, 'No tienes permisos para realizar esta operación.'), 'fallback')
    expect(spy).toHaveBeenCalledWith({ type: 'negative', message: 'fallback' })
  })

  it('uses the fallback for a non-ApiError', () => {
    const spy = vi.spyOn(Notify, 'create')
    notifyApiError(new Error('network blip'), 'fallback')
    expect(spy).toHaveBeenCalledWith({ type: 'negative', message: 'fallback' })
  })
})
