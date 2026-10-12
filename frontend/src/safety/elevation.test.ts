import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearElevationCache, fetchElevations } from './elevation'

afterEach(() => {
  vi.unstubAllGlobals()
  clearElevationCache()
})

function elevationResponse(elevations: number[]): Response {
  return new Response(JSON.stringify({ elevation: elevations }), {
    status: 200,
  })
}

function rateLimitedResponse(): Response {
  // Open-Meteoの実際の429レスポンス
  return new Response(
    JSON.stringify({
      reason: 'Minutely API request limit exceeded. Please try again in one minute.',
    }),
    { status: 429 },
  )
}

describe('fetchElevations: 429のリトライ', () => {
  it('1回目429・2回目200なら値が入り、sleepがretryWaitMsで1回呼ばれる', async () => {
    let callCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        callCount++
        return callCount === 1 ? rateLimitedResponse() : elevationResponse([321])
      }),
    )
    const sleep = vi.fn(async () => {})

    const result = await fetchElevations([{ lat: 42, lon: 143 }], undefined, {
      retryWaitMs: 61000,
      maxRetries: 1,
      sleep,
    })

    expect(result).toEqual([321])
    expect(callCount).toBe(2)
    expect(sleep).toHaveBeenCalledTimes(1)
    expect(sleep).toHaveBeenCalledWith(61000)
  })

  it('maxRetries回ともすべて429ならnullのまま', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => rateLimitedResponse()))
    const sleep = vi.fn(async () => {})

    const result = await fetchElevations([{ lat: 42, lon: 143 }], undefined, {
      maxRetries: 1,
      sleep,
    })

    expect(result).toEqual([null])
    // maxRetries=1なので待つのは1回だけ (2回目の429の後は待たない)
    expect(sleep).toHaveBeenCalledTimes(1)
  })

  it('429以外の失敗 (500) は待たずにnull', async () => {
    const sleep = vi.fn(async () => {})
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('err', { status: 500 })),
    )

    const result = await fetchElevations([{ lat: 42, lon: 143 }], undefined, {
      sleep,
    })

    expect(result).toEqual([null])
    expect(sleep).not.toHaveBeenCalled()
  })

  it('250点は3バッチに分かれる', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        calls.push(url)
        const n = url.split('latitude=')[1].split('&')[0].split(',').length
        return elevationResponse(Array.from({ length: n }, () => 10))
      }),
    )
    const points = Array.from({ length: 250 }, (_, i) => ({
      lat: 42 + i * 0.001,
      lon: 143 + i * 0.001,
    }))

    const result = await fetchElevations(points, undefined, {
      sleep: async () => {},
    })

    expect(calls).toHaveLength(3)
    expect(result.every((e) => e === 10)).toBe(true)
  })
})

describe('fetchElevations: 既存の動作 (キャッシュ/バッチ)', () => {
  it('150点を2リクエストに分割し、キャッシュする', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        calls.push(url)
        const n = url.split('latitude=')[1].split('&')[0].split(',').length
        return elevationResponse(Array.from({ length: n }, () => 123))
      }),
    )
    const points = Array.from({ length: 150 }, (_, i) => ({
      lat: 42 + i * 0.01,
      lon: 143 + i * 0.01,
    }))
    const result = await fetchElevations(points)
    expect(calls).toHaveLength(2)
    expect(result.every((e) => e === 123)).toBe(true)

    // 2回目はキャッシュヒットでリクエストなし
    const again = await fetchElevations(points.slice(0, 50))
    expect(calls).toHaveLength(2)
    expect(again.every((e) => e === 123)).toBe(true)
  })

  it('fetch失敗(ネットワーク例外)時はnull', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('network down')
      }),
    )
    const result = await fetchElevations([{ lat: 42, lon: 143 }])
    expect(result).toEqual([null])
  })
})
