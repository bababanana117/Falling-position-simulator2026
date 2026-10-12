import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setLandData } from './landSea'
import { scoreLanding, CATEGORY_PENALTY_KM } from './objectives'
import { setSafetyData } from '../safety/landingSafety'

// 北海道全域をカバーする矩形陸地 (テスト用: 139-146E, 41-46N)
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

beforeEach(() => {
  setLandData(hokkaidoLand)
  setSafetyData([], [])
})

afterEach(() => {
  setLandData(null)
  setSafetyData(null, null)
})

describe('scoreLanding safeLanding: unknown (標高取得失敗)', () => {
  it('elevationMがnullならcategory=unknown、ペナルティは山地と同じ', () => {
    const launch = { lat: 42.5, lon: 143.44 }
    const result = scoreLanding(
      { lat: 42.65, lon: 143.2 },
      launch,
      { kind: 'safeLanding' },
      null,
    )
    expect(result.category).toBe('unknown')
    expect(CATEGORY_PENALTY_KM.unknown).toBe(CATEGORY_PENALTY_KM.mountain)
  })
})
