import { describe, expect, it, vi } from 'vitest'
import {
  BACKEND_REQUIRED_MESSAGE,
  requestClimatology,
  toFlight,
  toInfo,
  toSampleFlights,
} from './climatology'
import type { ClimatologyRequest, ClimatologyResponse } from './climatology'

const LAUNCH = '2027-01-10T00:00:00.000Z'
const RES: ClimatologyResponse = {
  timebin: { month: 1, bin: 1, label: '1月前半', period: '2016–2025' },
  cell: { latitude: 33.7, longitude: 129.75, distance_km: 9.1 },
  mean_landing: { latitude: 33.9, longitude: 132.4 },
  covariance_m2: [[1e9, 0], [0, 4e8]],
  rho: 0.48,
  samples: [[33.8, 132.0], [34.0, 132.6]],
  trajectory: [
    { latitude: 33.78, longitude: 129.72, altitude: 0, time_s: 0 },
    { latitude: 33.8, longitude: 130.9, altitude: 30000, time_s: 6000 },
    { latitude: 33.9, longitude: 132.3, altitude: 0, time_s: 8200 },
  ],
  burst_index: 1,
  flight_time_s: 8200,
  warnings: [],
}
const REQ: ClimatologyRequest = {
  launch_latitude: 33.78, launch_longitude: 129.72, launch_altitude: 0,
  launch_datetime: LAUNCH, ascent_rate: 5, burst_altitude: 30000, descent_rate: 6,
  n_samples: 500, seed: 42,
}

describe('toFlight', () => {
  it('平均の軌道を上昇・降下に分け、時刻を付ける', () => {
    const f = toFlight(RES, LAUNCH)
    expect(f.ascent).toHaveLength(2)
    expect(f.descent).toHaveLength(2)
    expect(f.burst?.altitude).toBe(30000)
    expect(f.landing.longitude).toBe(132.3)
    expect(f.landing.datetime).toBe('2027-01-10T02:16:40.000Z')
    expect(f.flightTimeS).toBe(8200)
  })
})

describe('toSampleFlights', () => {
  it('標本ごとに着地点だけの Flight を作る', () => {
    const fs = toSampleFlights(RES, LAUNCH)
    expect(fs).toHaveLength(2)
    expect(fs[1].landing).toMatchObject({ latitude: 34.0, longitude: 132.6, altitude: 0 })
    expect(fs[1].launch.latitude).toBe(33.78)
    expect(fs[1].ascent).toEqual([])
  })
})

describe('toInfo', () => {
  it('表示用の情報', () => {
    expect(toInfo(RES)).toEqual({
      label: '1月前半', period: '2016–2025', cellLat: 33.7, cellLon: 129.75,
      cellDistanceKm: 9.1, rho: 0.48, warnings: [],
    })
  })
})

describe('requestClimatology', () => {
  it('バックエンドが無ければエラー', async () => {
    await expect(requestClimatology(REQ, { baseUrl: null })).rejects.toThrow(
      BACKEND_REQUIRED_MESSAGE,
    )
  })
  it('POST して JSON を返す。エラーは detail を出す', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(RES), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: '範囲外' }), { status: 422 }))
    vi.stubGlobal('fetch', fetchMock)
    const r = await requestClimatology(REQ, { baseUrl: 'http://x' })
    expect(r.rho).toBe(0.48)
    expect(fetchMock.mock.calls[0][0]).toBe('http://x/api/climatology/predict')
    await expect(requestClimatology(REQ, { baseUrl: 'http://x' })).rejects.toThrow('範囲外')
    vi.unstubAllGlobals()
  })
  it('検証エラーがリストなら msg を loc フィールド名付きで結合する', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: [
            { loc: ['body', 'ascent_rate'], msg: 'Input should be less than or equal to 15', type: 'less_than_equal' },
            { loc: ['body', 'burst_altitude'], msg: 'Input should be a valid integer', type: 'int_type' },
          ],
        }),
        { status: 422 },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    await expect(requestClimatology(REQ, { baseUrl: 'http://x' })).rejects.toThrow(
      'ascent_rate: Input should be less than or equal to 15 / burst_altitude: Input should be a valid integer',
    )
    vi.unstubAllGlobals()
  })
})
