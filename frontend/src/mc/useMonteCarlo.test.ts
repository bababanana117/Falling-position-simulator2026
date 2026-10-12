import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setLandData } from '../optimizer/landSea'
import { clearElevationCache } from '../safety/elevation'
import { emptyBreakdown, setSafetyData } from '../safety/landingSafety'
import { useResultsStore } from '../store/resultsStore'
import { commitSafetyResults, finishStatsAndSafety } from './useMonteCarlo'
import type { Flight } from '../api/tawhiriTypes'

// 北海道全域をカバーする矩形陸地 (他のテストと同じ座標、landSea.test.ts等を参照)
const hokkaidoLand = {
  features: [
    {
      geometry: {
        type: 'MultiPolygon' as const,
        coordinates: [
          [
            [
              [139, 41],
              [146, 41],
              [146, 46],
              [139, 46],
              [139, 41],
            ],
          ],
        ],
      },
    },
  ],
}

function flightAt(lat: number, lon: number): Flight {
  const p = { latitude: lat, longitude: lon, altitude: 0, datetime: '2026-01-01T00:00:00Z' }
  return {
    ascent: [],
    descent: [],
    launch: p,
    burst: null,
    landing: p,
    flightTimeS: 3600,
  }
}

beforeEach(() => {
  setLandData(hokkaidoLand)
  setSafetyData([], [])
  useResultsStore.getState().clearAll()
})

afterEach(() => {
  setLandData(null)
  setSafetyData(null, null)
  vi.unstubAllGlobals()
  clearElevationCache()
})

describe('commitSafetyResults', () => {
  it('isCurrent()がfalseなら何も書き込まない (キャンセル済み/上書き済みの実行を無視)', () => {
    const applyCategories = vi.fn()
    const setMcSafety = vi.fn()
    commitSafetyResults(
      { applyCategories, setMcSafety },
      () => false,
      new Map(),
      emptyBreakdown(),
    )
    expect(applyCategories).not.toHaveBeenCalled()
    expect(setMcSafety).not.toHaveBeenCalled()
  })

  it('isCurrent()がtrueなら書き込む', () => {
    const applyCategories = vi.fn()
    const setMcSafety = vi.fn()
    const categories = new Map([[0, 'safe' as const]])
    const breakdown = emptyBreakdown()
    commitSafetyResults(
      { applyCategories, setMcSafety },
      () => true,
      categories,
      breakdown,
    )
    expect(applyCategories).toHaveBeenCalledWith(categories)
    expect(setMcSafety).toHaveBeenCalledWith(breakdown)
  })
})

describe('finishStatsAndSafety: キャンセル済み/上書き済みの実行を無視', () => {
  it('標高取得が終わった時点でisCurrent()がfalseなら mcSafety/mcSamples のcategoryを変えない', async () => {
    const store = useResultsStore.getState()
    const samples = Array.from({ length: 5 }, (_, i) =>
      ({ index: i, flight: flightAt(42.65, 143.2), perturbed: { ascentRate: 5, burstAltitude: 30000, descentRate: 5 } }),
    )
    store.setMcSamples(samples)

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ elevation: [75, 75, 75, 75, 75] }), { status: 200 })),
    )

    // 実行中(isCurrent=true)に始まり、標高取得(await fetch)が終わる頃には
    // 新しい実行に上書きされた(isCurrent=false)、というキャンセル後の遅延到着を再現
    let current = true
    await finishStatsAndSafety(() => current)
    // ここではまだ書き込まれている (isCurrentは呼び出し時点でtrueだったので反映される)
    expect(useResultsStore.getState().mcSafety).not.toBeNull()

    // 次は最初からfalseのケース: 429リトライ待ちの間にcancel()されたのを模す
    useResultsStore.getState().setMcSafety(null)
    useResultsStore.getState().setMcSamples(samples)
    current = false
    await finishStatsAndSafety(() => current)
    expect(useResultsStore.getState().mcSafety).toBeNull()
    expect(
      useResultsStore.getState().mcSamples.every((s) => s.category === undefined),
    ).toBe(true)
  })
})
