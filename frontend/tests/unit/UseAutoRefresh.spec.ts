import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import {
  useAutoRefresh,
  AUTO_REFRESH_OPTIONS,
  DEFAULT_AUTO_REFRESH_MS,
  type AutoRefreshHandle,
} from '@/composables/useAutoRefresh'

const mountWith = (callback: () => void, defaultMs?: number) => {
  let handle!: AutoRefreshHandle
  const wrapper = mount(
    defineComponent({
      setup() {
        handle = defaultMs === undefined ? useAutoRefresh(callback) : useAutoRefresh(callback, defaultMs)
        return () => h('div')
      },
    }),
  )
  return { wrapper, handle: () => handle }
}

describe('useAutoRefresh', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('exposes AUTO_REFRESH_OPTIONS including the "off" (0ms) option', () => {
    expect(AUTO_REFRESH_OPTIONS.map((option) => option.value)).toContain(0)
  })

  it('defaults to DEFAULT_AUTO_REFRESH_MS and ticks the callback on that interval', async () => {
    const callback = vi.fn()
    const { handle } = mountWith(callback)
    expect(handle().intervalMs.value).toBe(DEFAULT_AUTO_REFRESH_MS)
    await vi.advanceTimersByTimeAsync(DEFAULT_AUTO_REFRESH_MS)
    expect(callback).toHaveBeenCalledTimes(1)
  })

  it('accepts an explicit default interval and ticks repeatedly', async () => {
    const callback = vi.fn()
    mountWith(callback, 5000)
    await vi.advanceTimersByTimeAsync(5000)
    expect(callback).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5000)
    expect(callback).toHaveBeenCalledTimes(2)
  })

  it('an interval of 0 ("off") never calls back', async () => {
    const callback = vi.fn()
    mountWith(callback, 0)
    await vi.advanceTimersByTimeAsync(60000)
    expect(callback).not.toHaveBeenCalled()
  })

  it('restarts on a new period when intervalMs is changed, and stop() halts ticking', async () => {
    const callback = vi.fn()
    const { handle } = mountWith(callback, 10000)
    handle().intervalMs.value = 1000
    await nextTick()
    await vi.advanceTimersByTimeAsync(1000)
    expect(callback).toHaveBeenCalledTimes(1)
    handle().stop()
    await vi.advanceTimersByTimeAsync(10000)
    expect(callback).toHaveBeenCalledTimes(1)
  })

  it('stops the interval automatically when the owning component unmounts', async () => {
    const callback = vi.fn()
    const { wrapper } = mountWith(callback, 1000)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(5000)
    expect(callback).not.toHaveBeenCalled()
  })
})
