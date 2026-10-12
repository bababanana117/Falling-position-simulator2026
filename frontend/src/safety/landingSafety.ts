// 着地点の安全カテゴリ判定 (北海道向け)
// 優先順: 海 → 空港/自衛隊(restricted) → 住宅街(towns近接) → 標高不明(unknown) → 山(標高閾値) → safe

import { haversineM } from '../stats/landing'
import { isOnLand } from '../optimizer/landSea'

export type SafetyCategory =
  | 'safe'
  | 'sea'
  | 'residential'
  | 'restricted'
  | 'mountain'
  | 'unknown'

export const CATEGORY_LABEL: Record<SafetyCategory, string> = {
  safe: '安全',
  sea: '海',
  residential: '住宅街',
  restricted: '空港/基地',
  mountain: '山地',
  unknown: '標高不明',
}

export const CATEGORY_COLOR: Record<SafetyCategory, string> = {
  safe: '#2e7d32',
  sea: '#1565c0',
  residential: '#ef6c00',
  restricted: '#c62828',
  mountain: '#6d4c41',
  unknown: '#9e9e9e',
}

export interface CircleZone {
  name: string
  lat: number
  lon: number
  radiusM: number
  kind: string
}

let towns: CircleZone[] | null = null
let restricted: CircleZone[] | null = null

export async function loadSafetyData(baseUrl = ''): Promise<void> {
  if (towns && restricted) return
  const [t, r] = await Promise.all([
    fetch(`${baseUrl}geo/towns.json`).then((res) => res.json()),
    fetch(`${baseUrl}geo/restricted.json`).then((res) => res.json()),
  ])
  towns = t as CircleZone[]
  restricted = r as CircleZone[]
}

/** テスト用注入 */
export function setSafetyData(
  t: CircleZone[] | null,
  r: CircleZone[] | null,
): void {
  towns = t
  restricted = r
}

export function getSafetyZones(): {
  towns: CircleZone[]
  restricted: CircleZone[]
} {
  return { towns: towns ?? [], restricted: restricted ?? [] }
}

function inAnyZone(lat: number, lon: number, zones: CircleZone[]): boolean {
  for (const z of zones) {
    // 粗い矩形プレフィルタ (1度≈111km)
    if (Math.abs(z.lat - lat) * 111000 > z.radiusM) continue
    if (haversineM({ lat, lon }, { lat: z.lat, lon: z.lon }) <= z.radiusM) {
      return true
    }
  }
  return false
}

export interface ClassifyOptions {
  /** これ以上の標高 [m] を「山地」と判定。既定500 */
  mountainElevationM?: number
}

/**
 * 着地点を安全カテゴリに分類する。
 * elevationM が null (429等で未取得) の場合は山判定ができないため 'unknown' を返す。
 * 以前はここで山判定をスキップして'safe'を返していたため、標高APIの
 * レート制限(429)で取れなかった点が安全着地率に紛れ込むバグがあった。
 */
export function classify(
  lat: number,
  lon: number,
  elevationM: number | null,
  opts: ClassifyOptions = {},
): SafetyCategory {
  const threshold = opts.mountainElevationM ?? 500
  if (!isOnLand(lat, lon)) return 'sea'
  if (restricted && inAnyZone(lat, lon, restricted)) return 'restricted'
  if (towns && inAnyZone(lat, lon, towns)) return 'residential'
  if (elevationM == null) return 'unknown'
  if (elevationM >= threshold) return 'mountain'
  return 'safe'
}

export type SafetyBreakdown = Record<SafetyCategory, number>

export function emptyBreakdown(): SafetyBreakdown {
  return {
    safe: 0,
    sea: 0,
    residential: 0,
    restricted: 0,
    mountain: 0,
    unknown: 0,
  }
}
