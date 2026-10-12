import { describe, expect, it } from 'vitest'
import {
  classifyLaunchTime,
  FORECAST_FUTURE_MS,
  FORECAST_PAST_MS,
} from './forecastWindow'

const NOW = Date.parse('2026-10-12T00:00:00Z')
const iso = (ms: number) => new Date(ms).toISOString()

describe('classifyLaunchTime', () => {
  it('予報窓の中は forecast', () => {
    expect(classifyLaunchTime(iso(NOW), NOW)).toEqual({ kind: 'forecast' })
    expect(classifyLaunchTime(iso(NOW + FORECAST_FUTURE_MS), NOW)).toEqual({ kind: 'forecast' })
    expect(classifyLaunchTime(iso(NOW - FORECAST_PAST_MS), NOW)).toEqual({ kind: 'forecast' })
  })
  it('+7 日より先は climatology', () => {
    expect(classifyLaunchTime(iso(NOW + FORECAST_FUTURE_MS + 1000), NOW)).toEqual({
      kind: 'climatology',
    })
    expect(classifyLaunchTime('2027-06-01T00:00:00Z', NOW)).toEqual({ kind: 'climatology' })
  })
  it('-12 時間より前はエラー', () => {
    const r = classifyLaunchTime(iso(NOW - FORECAST_PAST_MS - 1000), NOW)
    expect(r.kind).toBe('error')
  })
})
