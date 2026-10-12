// 発射時刻を「予報 (Tawhiri) / 統計 (気候値) / エラー」に分ける。
// Tawhiri (GFS) の予報窓は 現在 -12h 〜 +7日。それより先は統計モードで扱う。

export const FORECAST_PAST_MS = 12 * 3600 * 1000
export const FORECAST_FUTURE_MS = 7 * 24 * 3600 * 1000

export type LaunchTimeClass =
  | { kind: 'forecast' }
  | { kind: 'climatology' }
  | { kind: 'error'; message: string }

export function classifyLaunchTime(
  launchDatetimeIso: string,
  nowMs: number = Date.now(),
): LaunchTimeClass {
  const t = Date.parse(launchDatetimeIso)
  if (t < nowMs - FORECAST_PAST_MS) {
    return { kind: 'error', message: '発射時刻が過去すぎます (気象モデル範囲外)' }
  }
  if (t > nowMs + FORECAST_FUTURE_MS) return { kind: 'climatology' }
  return { kind: 'forecast' }
}
