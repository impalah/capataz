import { formatMetricValue } from '@/utils/format'

describe('formatMetricValue', () => {
  it('renders sub-100 values with one decimal', () => {
    expect(formatMetricValue(12.5)).toBe('12.5')
  })

  it('renders values of 100 or more with no decimals', () => {
    expect(formatMetricValue(512)).toBe('512')
    expect(formatMetricValue(-150)).toBe('-150')
  })

  it('returns a placeholder dash for null, undefined or non-finite input', () => {
    expect(formatMetricValue(null)).toBe('—')
    expect(formatMetricValue(undefined)).toBe('—')
    expect(formatMetricValue(Number.NaN)).toBe('—')
    expect(formatMetricValue(Number.POSITIVE_INFINITY)).toBe('—')
  })
})
