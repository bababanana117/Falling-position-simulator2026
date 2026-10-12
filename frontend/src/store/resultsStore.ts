import { create } from 'zustand'
import type { ClimatologyInfo } from '../api/climatology'
import type { Flight } from '../api/tawhiriTypes'
import type { GridResult } from '../optimizer/gridSearch'
import type { SafetyBreakdown, SafetyCategory } from '../safety/landingSafety'
import type { LandingStats } from '../stats/landing'

export interface HourlyResult {
  hourOffset: number
  flight: Flight
}

export interface MCSampleResult {
  index: number
  flight: Flight
  perturbed: { ascentRate: number; burstAltitude: number; descentRate: number }
  category?: SafetyCategory
}

export interface ResultsState {
  singleFlight: Flight | null
  hourlyResults: HourlyResult[]
  mcSamples: MCSampleResult[]
  mcCentral: Flight | null
  mcStats: LandingStats | null
  mcSafety: SafetyBreakdown | null
  optimizerResults: GridResult[]
  runError: string | null
  running: boolean
  progress: { done: number; total: number } | null
  mode: 'forecast' | 'climatology'
  climatologyInfo: ClimatologyInfo | null

  setSingle: (f: Flight | null) => void
  addHourly: (r: HourlyResult) => void
  clearHourly: () => void
  addMcSample: (s: MCSampleResult) => void
  setMcSamples: (samples: MCSampleResult[]) => void
  setMcCentral: (f: Flight | null) => void
  setMcStats: (s: LandingStats | null) => void
  setMcSafety: (b: SafetyBreakdown | null) => void
  applyCategories: (categories: Map<number, SafetyCategory>) => void
  setOptimizerResults: (r: GridResult[]) => void
  clearMc: () => void
  setError: (e: string | null) => void
  setRunning: (r: boolean) => void
  setProgress: (p: { done: number; total: number } | null) => void
  setClimatology: (info: ClimatologyInfo | null) => void
  clearAll: () => void
}

export const useResultsStore = create<ResultsState>((set) => ({
  singleFlight: null,
  hourlyResults: [],
  mcSamples: [],
  mcCentral: null,
  mcStats: null,
  mcSafety: null,
  optimizerResults: [],
  runError: null,
  running: false,
  progress: null,
  mode: 'forecast',
  climatologyInfo: null,

  setSingle: (f) => set({ singleFlight: f }),
  addHourly: (r) =>
    set((s) => ({ hourlyResults: [...s.hourlyResults, r] })),
  clearHourly: () => set({ hourlyResults: [] }),
  addMcSample: (sample) =>
    set((s) => ({ mcSamples: [...s.mcSamples, sample] })),
  setMcSamples: (samples) => set({ mcSamples: samples }),
  setMcCentral: (f) => set({ mcCentral: f }),
  setMcStats: (stats) => set({ mcStats: stats }),
  setMcSafety: (b) => set({ mcSafety: b }),
  setOptimizerResults: (r) => set({ optimizerResults: r }),
  applyCategories: (categories) =>
    set((s) => ({
      mcSamples: s.mcSamples.map((sample) => ({
        ...sample,
        category: categories.get(sample.index) ?? sample.category,
      })),
    })),
  clearMc: () =>
    set({ mcSamples: [], mcCentral: null, mcStats: null, mcSafety: null }),
  setError: (e) => set({ runError: e }),
  setRunning: (r) => set({ running: r }),
  setProgress: (p) => set({ progress: p }),
  setClimatology: (info) =>
    set({ climatologyInfo: info, mode: info ? 'climatology' : 'forecast' }),
  clearAll: () =>
    set({
      singleFlight: null,
      hourlyResults: [],
      mcSamples: [],
      mcCentral: null,
      mcStats: null,
      mcSafety: null,
      runError: null,
      progress: null,
      mode: 'forecast',
      climatologyInfo: null,
    }),
}))
