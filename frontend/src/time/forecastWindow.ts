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

// GitHub Pages 配信 (バックエンド無し) では統計モードを謳わず・使わせない。
// classifyLaunchTime の結果とバックエンドの有無から、実際にどちらのモードで動くか
// (またはエラーにするか) を決める純粋関数。副作用 (clearAll 等) は呼び出し側の責任。
export function resolveLaunchMode(
  cls: LaunchTimeClass,
  backendEnabled: boolean,
): { kind: 'forecast' } | { kind: 'climatology' } | { kind: 'error'; message: string } {
  if (cls.kind === 'error') return cls
  if (cls.kind === 'forecast') return { kind: 'forecast' }
  // cls.kind === 'climatology'
  if (!backendEnabled) {
    return {
      kind: 'error',
      message:
        '発射時刻が未来すぎます（予報は 7 日先まで。統計モードはバックエンド付きの環境でのみ使えます）',
    }
  }
  return { kind: 'climatology' }
}
