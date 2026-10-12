import { describe, expect, it } from 'vitest'
import {
  classifyLaunchTime,
  FORECAST_FUTURE_MS,
  FORECAST_PAST_MS,
  resolveLaunchMode,
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

describe('resolveLaunchMode', () => {
  it('forecast はバックエンドの有無に関わらず forecast', () => {
    expect(resolveLaunchMode({ kind: 'forecast' }, true)).toEqual({ kind: 'forecast' })
    expect(resolveLaunchMode({ kind: 'forecast' }, false)).toEqual({ kind: 'forecast' })
  })
  it('過去すぎエラーはバックエンドの有無に関わらずそのまま通す', () => {
    const err = { kind: 'error' as const, message: '発射時刻が過去すぎます (気象モデル範囲外)' }
    expect(resolveLaunchMode(err, true)).toEqual(err)
    expect(resolveLaunchMode(err, false)).toEqual(err)
  })
  it('climatology はバックエンドがあれば climatology', () => {
    expect(resolveLaunchMode({ kind: 'climatology' }, true)).toEqual({ kind: 'climatology' })
  })
  it('climatology はバックエンドが無ければエラー', () => {
    const r = resolveLaunchMode({ kind: 'climatology' }, false)
    expect(r.kind).toBe('error')
    expect(r.kind === 'error' && r.message).toBe(
      '発射時刻が未来すぎます（予報は 7 日先まで。統計モードはバックエンド付きの環境でのみ使えます）',
    )
  })
})
