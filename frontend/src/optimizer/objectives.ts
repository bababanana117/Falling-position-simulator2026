import { haversineM } from '../stats/landing'
import type { LatLon } from '../stats/landing'
import { classify } from '../safety/landingSafety'
import type { SafetyCategory } from '../safety/landingSafety'
import { isOnLand } from './landSea'

export interface ObjectiveConfig {
  kind: 'avoidSea' | 'minDistance' | 'safeLanding'
  /** minDistance時の回収目標地点 */
  target?: LatLon
  /** 海着水時のペナルティ [km] (スコアに加算される距離相当) */
  seaPenaltyKm?: number
  /** safeLanding: 山判定の標高閾値 [m] (既定500) */
  mountainElevationM?: number
}

export interface ScoredLanding {
  score: number // 小さいほど良い
  onLand: boolean
  distanceKm: number | null
  category?: SafetyCategory
}

/** safeLanding用カテゴリペナルティ [km相当] */
export const CATEGORY_PENALTY_KM: Record<SafetyCategory, number> = {
  safe: 0,
  mountain: 300,
  residential: 1000,
  restricted: 1500,
  sea: 1000,
  // 標高が取得できなかった点 (429等) は山地と同じ扱い。
  // 分からない点を最良候補として選ばないようにするため
  unknown: 300,
}

/**
 * 着地点を採点する。スコアは「小さいほど良い」距離ベースの値 [km]。
 * - minDistance: 目標地点までの距離 + 海ペナルティ
 * - avoidSea: 海なら大ペナルティ、陸なら発射地点からの距離
 * - safeLanding: カテゴリペナルティ (海/住宅街/空港基地/山/標高不明) + 発射地点からの距離。
 *   elevationM未取得(null)時は'unknown'(山地と同じペナルティ)
 */
export function scoreLanding(
  landing: LatLon,
  launch: LatLon,
  config: ObjectiveConfig,
  elevationM: number | null = null,
): ScoredLanding {
  const seaPenalty = config.seaPenaltyKm ?? 1000

  if (config.kind === 'safeLanding') {
    const category = classify(landing.lat, landing.lon, elevationM, {
      mountainElevationM: config.mountainElevationM,
    })
    const dist = haversineM(landing, launch) / 1000
    return {
      score: CATEGORY_PENALTY_KM[category] + dist,
      onLand: category !== 'sea',
      distanceKm: dist,
      category,
    }
  }

  const onLand = isOnLand(landing.lat, landing.lon)

  if (config.kind === 'avoidSea') {
    const dist = haversineM(landing, launch) / 1000
    return {
      score: onLand ? dist : seaPenalty + dist,
      onLand,
      distanceKm: dist,
    }
  }

  const target = config.target ?? launch
  const dist = haversineM(landing, target) / 1000
  return {
    score: dist + (onLand ? 0 : seaPenalty),
    onLand,
    distanceKm: dist,
  }
}
