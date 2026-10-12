import { useCallback, useRef } from 'react'
import { backendEnabled } from '../api/backend'
import { requestClimatology, toFlight, toInfo } from '../api/climatology'
import type { ClimatologyRequest } from '../api/climatology'
import { requestPrediction } from '../api/tawhiri'
import type { TawhiriRequest } from '../api/tawhiriTypes'
import { TawhiriError } from '../api/tawhiriTypes'
import { jitterMs, tawhiriSemaphore } from '../api/semaphore'
import { classifyLaunchTime, resolveLaunchMode } from '../time/forecastWindow'
import { jstInputToUtcIso } from '../time/jst'
import { useParamsStore } from '../store/paramsStore'
import { useResultsStore } from '../store/resultsStore'

export function buildBaseRequest(): TawhiriRequest {
  const p = useParamsStore.getState()
  const launchDatetime = jstInputToUtcIso(p.launchTimeJst)
  if (p.profile === 'standard_profile') {
    return {
      profile: 'standard_profile',
      launch_latitude: p.latitude,
      launch_longitude: p.longitude,
      launch_altitude: p.launchAltitude,
      launch_datetime: launchDatetime,
      ascent_rate: p.ascentRate,
      burst_altitude: p.burstAltitude,
      descent_rate: p.descentRate,
    }
  }
  const stop = new Date(Date.parse(launchDatetime) + 24 * 3600 * 1000)
  return {
    profile: 'float_profile',
    launch_latitude: p.latitude,
    launch_longitude: p.longitude,
    launch_altitude: p.launchAltitude,
    launch_datetime: launchDatetime,
    ascent_rate: p.ascentRate,
    float_altitude: p.burstAltitude,
    stop_datetime: stop.toISOString(),
  }
}

/** 発射時刻の妥当性チェック (GFSモデル窓: 現在-12h 〜 +7日)。毎時モード用 */
export function validateLaunchTime(launchDatetimeIso: string): string | null {
  const c = classifyLaunchTime(launchDatetimeIso)
  if (c.kind === 'error') return c.message
  if (c.kind === 'climatology') return '発射時刻が未来すぎます (気象モデル範囲外)'
  return null
}

/** 統計モードのリクエスト (フォームの値から) */
export function buildClimatologyRequest(nSamples: number, seed: number): ClimatologyRequest {
  const p = useParamsStore.getState()
  return {
    launch_latitude: p.latitude,
    launch_longitude: p.longitude,
    launch_altitude: p.launchAltitude,
    launch_datetime: jstInputToUtcIso(p.launchTimeJst),
    ascent_rate: p.ascentRate,
    burst_altitude: p.burstAltitude,
    descent_rate: p.descentRate,
    n_samples: nSamples,
    seed,
  }
}

export function useRunPrediction() {
  const abortRef = useRef<AbortController | null>(null)

  const cancel = useCallback(() => {
    abortRef.current?.abort()
    useResultsStore.getState().setRunning(false)
  }, [])

  const runSingle = useCallback(async () => {
    const results = useResultsStore.getState()
    const req = buildBaseRequest()
    const cls = resolveLaunchMode(classifyLaunchTime(req.launch_datetime), backendEnabled())
    if (cls.kind === 'error') {
      // clearAll() より前に出す: バックエンド無しで統計モード域に入った場合も
      // それまでの結果を残す
      results.setError(cls.message)
      return
    }
    abortRef.current = new AbortController()
    results.clearAll()
    results.setRunning(true)
    try {
      if (cls.kind === 'climatology') {
        if (req.profile !== 'standard_profile') {
          throw new Error('統計モードは標準プロファイルのみ対応です')
        }
        const res = await requestClimatology(buildClimatologyRequest(10, 42), {
          signal: abortRef.current.signal,
        })
        results.setSingle(toFlight(res, req.launch_datetime))
        useResultsStore.getState().setClimatology(toInfo(res))
      } else {
        const flight = await tawhiriSemaphore.run(() =>
          requestPrediction(req, { signal: abortRef.current!.signal }),
        )
        results.setSingle(flight)
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) {
        results.setError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      results.setRunning(false)
    }
  }, [])

  const runHourly = useCallback(async () => {
    const results = useResultsStore.getState()
    const params = useParamsStore.getState()
    const base = buildBaseRequest()
    const err = validateLaunchTime(base.launch_datetime)
    if (err) {
      results.setError(err)
      return
    }
    abortRef.current = new AbortController()
    const signal = abortRef.current.signal
    results.clearAll()
    results.setRunning(true)

    const offsets: number[] = []
    for (let h = 0; h <= params.hourlyDurationH; h += params.hourlyStepH) {
      offsets.push(h)
    }
    results.setProgress({ done: 0, total: offsets.length })
    let done = 0

    await Promise.all(
      offsets.map(async (hourOffset) => {
        await new Promise((r) => setTimeout(r, jitterMs()))
        const launch = new Date(
          Date.parse(base.launch_datetime) + hourOffset * 3600 * 1000,
        ).toISOString()
        const req = { ...base, launch_datetime: launch } as TawhiriRequest
        try {
          const flight = await tawhiriSemaphore.run(() =>
            requestPrediction(req, { signal }),
          )
          useResultsStore.getState().addHourly({ hourOffset, flight })
        } catch (e) {
          // モデル窓を超えた時刻は静かにスキップ (旧実装と同じ挙動)
          if (e instanceof DOMException && e.name === 'AbortError') return
          if (e instanceof TawhiriError && e.status === 429) {
            tawhiriSemaphore.pause(10000)
          }
        } finally {
          done++
          useResultsStore.getState().setProgress({ done, total: offsets.length })
        }
      }),
    )
    useResultsStore.getState().setRunning(false)
  }, [])

  return { runSingle, runHourly, cancel }
}
