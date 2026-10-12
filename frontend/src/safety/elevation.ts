// Open-Meteo Elevation API クライアント (バッチ最大100点/リクエスト、キャッシュ付き)
// 無料枠は「1分あたり」の上限があり、100点超のリクエストを続けて送ると
// 429 (Minutely API request limit exceeded) が返ることがある。
// その場合はretryWaitMs待って同じバッチだけやり直す (最大maxRetries回)。

export const ELEVATION_API = 'https://api.open-meteo.com/v1/elevation'
const BATCH_SIZE = 100

const cache = new Map<string, number>()

function key(lat: number, lon: number): string {
  // ~110m解像度でキャッシュ (APIの解像度は90m)
  return `${lat.toFixed(3)},${lon.toFixed(3)}`
}

export function clearElevationCache(): void {
  cache.clear()
}

export interface FetchElevationsOptions {
  /** 429のときに待つ時間 [ms]。既定61000 (レート制限が1分単位のため) */
  retryWaitMs?: number
  /** 429のときのリトライ回数。既定1 (計2回まで試す) */
  maxRetries?: number
  /** 待機の実装。テスト用に差し替え可能。既定はsetTimeoutベース */
  sleep?: (ms: number) => Promise<void>
  /** リトライ待機中に呼ばれる (UI通知用、省略可) */
  onWait?: (ms: number) => void
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * 複数地点の標高 [m] を一括取得。結果は入力順の配列。
 * 429 (レート制限) 以外の失敗、および429をmaxRetries回リトライしても
 * 失敗した場合は該当要素が null (呼び出し側は'unknown'として扱う)。
 */
export async function fetchElevations(
  points: { lat: number; lon: number }[],
  baseUrl = ELEVATION_API,
  opts: FetchElevationsOptions = {},
): Promise<(number | null)[]> {
  const retryWaitMs = opts.retryWaitMs ?? 61000
  const maxRetries = opts.maxRetries ?? 1
  const sleep = opts.sleep ?? defaultSleep

  const result: (number | null)[] = new Array(points.length).fill(null)
  const missing: number[] = []

  points.forEach((p, i) => {
    const cached = cache.get(key(p.lat, p.lon))
    if (cached !== undefined) {
      result[i] = cached
    } else {
      missing.push(i)
    }
  })

  for (let start = 0; start < missing.length; start += BATCH_SIZE) {
    const batch = missing.slice(start, start + BATCH_SIZE)
    const lats = batch.map((i) => points[i].lat.toFixed(5)).join(',')
    const lons = batch.map((i) => points[i].lon.toFixed(5)).join(',')
    const url = `${baseUrl}?latitude=${lats}&longitude=${lons}`

    for (let attempt = 0; ; attempt++) {
      try {
        const res = await fetch(url)
        if (res.status === 429 && attempt < maxRetries) {
          opts.onWait?.(retryWaitMs)
          await sleep(retryWaitMs)
          continue
        }
        if (!res.ok) break
        const body = (await res.json()) as { elevation: number[] }
        batch.forEach((pointIndex, j) => {
          const elev = body.elevation[j]
          if (typeof elev === 'number') {
            result[pointIndex] = elev
            cache.set(
              key(points[pointIndex].lat, points[pointIndex].lon),
              elev,
            )
          }
        })
        break
      } catch {
        // ネットワーク失敗時はnullのまま (呼び出し側は'unknown'として扱う)
        break
      }
    }
  }
  return result
}
