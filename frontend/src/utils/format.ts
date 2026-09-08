export function formatMetricValue(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return value.toFixed(Math.abs(value) >= 100 ? 0 : 1)
}
