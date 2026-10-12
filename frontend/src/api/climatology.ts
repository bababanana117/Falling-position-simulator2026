// 統計モード (気候値) のクライアント。バックエンドの POST /api/climatology/predict を呼び、
// 結果をアプリ共通の Flight とモンテカルロの落下点に直す。
// スキーマは backend/bfps/models/schemas.py の ClimatologyRequest / ClimatologyResponse と対応。

import { backendBaseUrl } from './backend'
import type { Flight, TrajectoryPoint } from './tawhiriTypes'

export const BACKEND_REQUIRED_MESSAGE =
  '統計モードにはバックエンドが必要です（VITE_API_BASE を設定してください）'

export interface ClimatologyRequest {
  launch_latitude: number
  launch_longitude: number
  launch_altitude: number
  launch_datetime: string
  ascent_rate: number
  burst_altitude: number
  descent_rate: number
  n_samples: number
  seed: number
}

export interface ClimatologyResponse {
  timebin: { month: number; bin: number; label: string; period: string }
  cell: { latitude: number; longitude: number; distance_km: number }
  mean_landing: { latitude: number; longitude: number }
  covariance_m2: number[][]
  rho: number
  samples: number[][]
  trajectory: { latitude: number; longitude: number; altitude: number; time_s: number }[]
  burst_index: number
  flight_time_s: number
  warnings: string[]
}

export interface ClimatologyInfo {
  label: string
  period: string
  cellLat: number
  cellLon: number
  cellDistanceKm: number
  rho: number
  warnings: string[]
}

export async function requestClimatology(
  req: ClimatologyRequest,
  opts: { signal?: AbortSignal; baseUrl?: string | null } = {},
): Promise<ClimatologyResponse> {
  const base = opts.baseUrl === undefined ? backendBaseUrl() : opts.baseUrl
  if (!base) throw new Error(BACKEND_REQUIRED_MESSAGE)
  const res = await fetch(`${base}/api/climatology/predict`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(req),
    signal: opts.signal,
  })
  if (!res.ok) {
    let detail = `統計モードの計算に失敗しました (HTTP ${res.status})`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // 本文が JSON でなければ既定の文言
    }
    throw new Error(detail)
  }
  return (await res.json()) as ClimatologyResponse
}

function atTime(launchIso: string, seconds: number): string {
  return new Date(Date.parse(launchIso) + seconds * 1000).toISOString()
}

export function toFlight(res: ClimatologyResponse, launchIso: string): Flight {
  const pts: TrajectoryPoint[] = res.trajectory.map((p) => ({
    latitude: p.latitude,
    longitude: p.longitude,
    altitude: p.altitude,
    datetime: atTime(launchIso, p.time_s),
  }))
  const b = res.burst_index
  return {
    ascent: pts.slice(0, b + 1),
    descent: pts.slice(b),
    launch: pts[0],
    burst: pts[b],
    landing: pts[pts.length - 1],
    flightTimeS: res.flight_time_s,
  }
}

export function toSampleFlights(res: ClimatologyResponse, launchIso: string): Flight[] {
  const launch: TrajectoryPoint = {
    latitude: res.trajectory[0].latitude,
    longitude: res.trajectory[0].longitude,
    altitude: res.trajectory[0].altitude,
    datetime: launchIso,
  }
  const landingTime = atTime(launchIso, res.flight_time_s)
  return res.samples.map(([lat, lon]) => ({
    ascent: [],
    descent: [],
    launch,
    burst: null,
    landing: { latitude: lat, longitude: lon, altitude: 0, datetime: landingTime },
    flightTimeS: res.flight_time_s,
  }))
}

export function toInfo(res: ClimatologyResponse): ClimatologyInfo {
  return {
    label: res.timebin.label,
    period: res.timebin.period,
    cellLat: res.cell.latitude,
    cellLon: res.cell.longitude,
    cellDistanceKm: res.cell.distance_km,
    rho: res.rho,
    warnings: res.warnings,
  }
}
