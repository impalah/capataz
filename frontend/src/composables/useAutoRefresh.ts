import { onBeforeUnmount, ref, watch, type Ref } from 'vue'

export interface AutoRefreshOption {
  label: string
  value: number
}

/** 0 means "off" (the '—' option); other values are milliseconds. */
export const AUTO_REFRESH_OPTIONS: AutoRefreshOption[] = [
  { label: '—', value: 0 },
  { label: '5s', value: 5000 },
  { label: '10s', value: 10000 },
  { label: '30s', value: 30000 },
  { label: '1 min', value: 60000 },
]

export const DEFAULT_AUTO_REFRESH_MS = 30000

export interface AutoRefreshHandle {
  intervalMs: Ref<number>
  stop: () => void
  start: () => void
}

/** Runs `callback` on a user-selectable interval; call `stop()` to end it early (e.g. once a watched task reaches a terminal state). */
export function useAutoRefresh(
  callback: () => void | Promise<void>,
  defaultMs: number = DEFAULT_AUTO_REFRESH_MS,
): AutoRefreshHandle {
  const intervalMs = ref(defaultMs)
  let handle: ReturnType<typeof setInterval> | undefined

  const stop = (): void => {
    if (handle !== undefined) {
      clearInterval(handle)
      handle = undefined
    }
  }
  const start = (): void => {
    stop()
    if (intervalMs.value > 0) handle = setInterval(() => void callback(), intervalMs.value)
  }

  watch(intervalMs, start)
  start()
  onBeforeUnmount(stop)

  return { intervalMs, stop, start }
}
