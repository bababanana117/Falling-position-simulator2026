import { useCallback, useRef } from 'react'
import { requestClimatology, toFlight, toInfo, toSampleFlights } from '../api/climatology'
import { MAX_CONCURRENT_TAWHIRI, tawhiriSemaphore } from '../api/semaphore'
import { requestPrediction } from '../api/tawhiri'
import { buildClimatologyRequest } from '../hooks/useRunPrediction'
import { loadLandData } from '../optimizer/landSea'
import { fetchElevations } from '../safety/elevation'
import {
  classify,
  emptyBreakdown,
  loadSafetyData,
} from '../safety/landingSafety'
import type { SafetyBreakdown, SafetyCategory } from '../safety/landingSafety'
import { computeLandingStats } from '../stats/landing'
import { useResultsStore } from '../store/resultsStore'
import type { ResultsState } from '../store/resultsStore'
import { partitionIndices } from './sampling'
import type { MCConfig, MCWorkerReply } from './mcTypes'

export const MC_MAX_SAMPLES = 500

/**
 * ストア書き込みをisCurrent()で守るヘルパー (テスト用に分離)。
 * isCurrent()がfalse (キャンセル済み/新しい実行に上書きされた) を返すときは
 * 何も書き込まない。
 */
export function commitSafetyResults(
  store: Pick<ResultsState, 'applyCategories' | 'setMcSafety'>,
  isCurrent: () => boolean,
  categories: Map<number, SafetyCategory>,
  breakdown: SafetyBreakdown,
): void {
  if (!isCurrent()) return
  store.applyCategories(categories)
  store.setMcSafety(breakdown)
}

/**
 * 統計計算 (landings の集計) と安全判定 (陸海/除外区域データ+標高)。
 * 429のリトライ待ち (最大retryWaitMs×maxRetries、既定で61〜122秒) の間に
 * cancel() や新しい実行が始まっている場合、isCurrent() がfalseを返すので
 * 古い実行の結果でストアを上書きしない。
 */
export async function finishStatsAndSafety(isCurrent: () => boolean): Promise<void> {
  const store = useResultsStore.getState()
  const landings = store.mcSamples.map((s) => ({
    lat: s.flight.landing.latitude,
    lon: s.flight.landing.longitude,
  }))
  if (landings.length >= 5 && isCurrent()) {
    store.setMcStats(computeLandingStats(landings))
  }
  try {
    const baseUrl = import.meta.env.BASE_URL
    await Promise.all([loadLandData(baseUrl), loadSafetyData(baseUrl)])
    const samplesSnapshot = useResultsStore.getState().mcSamples
    const elevations = await fetchElevations(
      samplesSnapshot.map((s) => ({
        lat: s.flight.landing.latitude,
        lon: s.flight.landing.longitude,
      })),
    )
    const categories = new Map<number, SafetyCategory>()
    const breakdown = emptyBreakdown()
    samplesSnapshot.forEach((s, i) => {
      const cat = classify(s.flight.landing.latitude, s.flight.landing.longitude, elevations[i])
      categories.set(s.index, cat)
      breakdown[cat]++
    })
    commitSafetyResults(useResultsStore.getState(), isCurrent, categories, breakdown)
  } catch {
    // 安全判定はベストエフォート (データ取得失敗でもMC結果自体は有効)
  }
}

export function useMonteCarlo() {
  const workersRef = useRef<Worker[]>([])
  const climAbortRef = useRef<AbortController | null>(null)
  // run()/runClimatology() 共通の実行世代。キャンセル後や新しい実行が始まった後に
  // 古いfetchやfinishStatsAndSafetyの429リトライ待ち(最大61〜122秒)が遅れて
  // 返ってきても、ストアへの書き込みをしないようにする
  const genRef = useRef(0)

  const cancel = useCallback(() => {
    for (const w of workersRef.current) {
      w.postMessage({ type: 'cancel' })
      w.terminate()
    }
    workersRef.current = []
    climAbortRef.current?.abort()
    genRef.current++
    useResultsStore.getState().setRunning(false)
  }, [])

  const run = useCallback(
    async (config: MCConfig) => {
      const myGen = ++genRef.current
      const results = useResultsStore.getState()
      const samples = Math.min(config.samples, MC_MAX_SAMPLES)
      results.clearAll()
      results.setRunning(true)
      results.setProgress({ done: 0, total: samples + 1 })

      // 中心点 (摂動なし) はメインスレッドで実行
      try {
        const central = await tawhiriSemaphore.run(() =>
          requestPrediction(config.base),
        )
        useResultsStore.getState().setMcCentral(central)
      } catch (e) {
        useResultsStore
          .getState()
          .setError(e instanceof Error ? e.message : String(e))
        useResultsStore.getState().setRunning(false)
        return
      }

      const poolSize = Math.min(4, navigator.hardwareConcurrency ?? 2)
      const partitions = partitionIndices(samples, poolSize)
      // グローバル上限5をworker数で分配
      const perWorkerConcurrency = Math.max(
        1,
        Math.floor(MAX_CONCURRENT_TAWHIRI / partitions.length),
      )

      let done = 1 // 中心点分
      let finishedWorkers = 0

      await new Promise<void>((resolve) => {
        workersRef.current = partitions.map((indices) => {
          const worker = new Worker(
            new URL('./mcWorker.ts', import.meta.url),
            { type: 'module' },
          )
          worker.onmessage = (ev: MessageEvent<MCWorkerReply>) => {
            const msg = ev.data
            const store = useResultsStore.getState()
            if (msg.type === 'sample') {
              store.addMcSample({
                index: msg.index,
                flight: msg.flight,
                perturbed: {
                  ascentRate: msg.perturbed.ascentRate,
                  burstAltitude: msg.perturbed.burstAltitude,
                  descentRate: msg.perturbed.descentRate,
                },
              })
              done++
              store.setProgress({ done, total: samples + 1 })
            } else if (msg.type === 'error') {
              done++
              store.setProgress({ done, total: samples + 1 })
            } else if (msg.type === 'done') {
              finishedWorkers++
              if (finishedWorkers === partitions.length) resolve()
            }
          }
          worker.postMessage({
            type: 'run',
            config: { ...config, samples },
            indices,
            concurrency: perWorkerConcurrency,
          })
          return worker
        })
      })

      for (const w of workersRef.current) w.terminate()
      workersRef.current = []

      await finishStatsAndSafety(() => genRef.current === myGen)
      if (genRef.current === myGen) useResultsStore.getState().setRunning(false)
    },
    [],
  )

  const runClimatology = useCallback(async (nSamples: number, seed: number) => {
    const results = useResultsStore.getState()
    const myGen = ++genRef.current
    const controller = new AbortController()
    climAbortRef.current = controller
    results.clearAll()
    results.setRunning(true)
    try {
      // 統計モードも標高API(Open-Meteo)の1分あたりのレート制限に当たるため、
      // フロント側の上限は通常モードと同じMC_MAX_SAMPLESにする (バックエンドのn_samples上限2000は変えない)
      const req = buildClimatologyRequest(
        Math.min(MC_MAX_SAMPLES, Math.max(10, nSamples)),
        seed,
      )
      const res = await requestClimatology(req, { signal: controller.signal })
      if (genRef.current !== myGen) return // キャンセル済み/上書き済み
      const store = useResultsStore.getState()
      store.setMcCentral(toFlight(res, req.launch_datetime))
      const perturbed = {
        ascentRate: req.ascent_rate,
        burstAltitude: req.burst_altitude,
        descentRate: req.descent_rate,
      }
      store.setMcSamples(
        toSampleFlights(res, req.launch_datetime).map((flight, index) => ({
          index,
          flight,
          perturbed,
        })),
      )
      store.setClimatology(toInfo(res))
      if (genRef.current !== myGen) return
      await finishStatsAndSafety(() => genRef.current === myGen)
      if (genRef.current !== myGen) return
    } catch (e) {
      if (genRef.current !== myGen) return
      if (e instanceof DOMException && e.name === 'AbortError') return
      useResultsStore.getState().setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (genRef.current === myGen) useResultsStore.getState().setRunning(false)
    }
  }, [])

  return { run, runClimatology, cancel }
}
