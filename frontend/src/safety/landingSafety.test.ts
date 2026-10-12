import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setLandData } from '../optimizer/landSea'
import { scoreLanding, CATEGORY_PENALTY_KM } from '../optimizer/objectives'
import { classify, setSafetyData } from './landingSafety'

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

const testTowns = [
  { name: '帯広', lat: 42.9236, lon: 143.1966, radiusM: 5000, kind: 'city' },
]
const testRestricted = [
  {
    name: '新千歳空港',
    lat: 42.7752,
    lon: 141.6923,
    radiusM: 7000,
    kind: 'airport',
  },
]

beforeEach(() => {
  setLandData(hokkaidoLand)
  setSafetyData(testTowns, testRestricted)
})

afterEach(() => {
  setLandData(null)
  setSafetyData(null, null)
})

describe('classify', () => {
  it('sea: 陸地ポリゴン外', () => {
    expect(classify(41.5, 148.0, 10)).toBe('sea') // 太平洋沖
  })

  it('restricted: 新千歳空港近傍', () => {
    expect(classify(42.78, 141.69, 20)).toBe('restricted')
  })

  it('residential: 帯広市街', () => {
    expect(classify(42.9236, 143.1966, 40)).toBe('residential')
  })

  it('mountain: 標高閾値超え', () => {
    expect(classify(43.3, 142.9, 1200)).toBe('mountain')
  })

  it('mountain閾値はオプションで変更可能', () => {
    expect(classify(43.3, 142.9, 450, { mountainElevationM: 400 })).toBe(
      'mountain',
    )
    expect(classify(43.3, 142.9, 450, { mountainElevationM: 500 })).toBe(
      'safe',
    )
  })

  it('safe: 十勝平野の農地相当', () => {
    expect(classify(42.65, 143.2, 75)).toBe('safe')
  })

  it('標高null時は「不明」(429等で取得できなかった点を安全に数えない)', () => {
    // 以前は山判定をスキップして'safe'を返していたが、429で取得できなかった点を
    // 安全着地率に混ぜてしまうバグだったため'unknown'に変更
    expect(classify(43.3, 142.9, null)).toBe('unknown')
  })

  it('標高null時でも海判定は変わらない', () => {
    expect(classify(41.5, 148.0, null)).toBe('sea')
  })

  it('優先順: restrictedはresidentialより先', () => {
    // 空港円内かつ町円内の点を作る
    setSafetyData(
      [{ name: 'x', lat: 42.775, lon: 141.69, radiusM: 10000, kind: 'city' }],
      testRestricted,
    )
    expect(classify(42.78, 141.69, 10)).toBe('restricted')
  })
})

describe('scoreLanding safeLanding', () => {
  const launch = { lat: 42.5, lon: 143.44 }

  it('ペナルティ順: restricted > sea ≈ residential > mountain > safe', () => {
    const safe = scoreLanding({ lat: 42.65, lon: 143.2 }, launch, {
      kind: 'safeLanding',
    }, 75)
    const mountain = scoreLanding({ lat: 43.3, lon: 142.9 }, launch, {
      kind: 'safeLanding',
    }, 1200)
    const residential = scoreLanding({ lat: 42.9236, lon: 143.1966 }, launch, {
      kind: 'safeLanding',
    }, 40)
    const sea = scoreLanding({ lat: 41.5, lon: 148.0 }, launch, {
      kind: 'safeLanding',
    }, 0)
    const restricted = scoreLanding({ lat: 42.78, lon: 141.69 }, launch, {
      kind: 'safeLanding',
    }, 20)

    expect(safe.category).toBe('safe')
    expect(mountain.category).toBe('mountain')
    expect(residential.category).toBe('residential')
    expect(sea.category).toBe('sea')
    expect(restricted.category).toBe('restricted')

    expect(safe.score).toBeLessThan(mountain.score)
    expect(mountain.score).toBeLessThan(residential.score)
    expect(residential.score).toBeLessThan(restricted.score)
  })

  it('ペナルティ定数の順序', () => {
    expect(CATEGORY_PENALTY_KM.safe).toBe(0)
    expect(CATEGORY_PENALTY_KM.mountain).toBeLessThan(
      CATEGORY_PENALTY_KM.residential,
    )
    expect(CATEGORY_PENALTY_KM.residential).toBeLessThan(
      CATEGORY_PENALTY_KM.restricted,
    )
  })
})
// fetchElevationsのテストは safety/elevation.test.ts に移動 (429リトライ追加に伴い分離)
