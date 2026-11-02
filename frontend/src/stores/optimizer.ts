import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'
import { getApiErrorMessage } from '../utils/errors'

const api = axios.create({
  baseURL: import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
})

export type OptimizerMode = 'scan' | 'apply' | 'verify'

export interface OptimizerConfig {
  enabled: boolean
  max_width: number
  max_height: number
  quality: number
  pic_dir: string
}

export interface OptimizerRunResult {
  mode: string
  analyzed: number
  resized: number
  already_ok: number
  skipped_unsupported: number
  errors: number
  bytes_before: number
  bytes_after: number
  bytes_saved: number
  duration_s: number
  ok: boolean
  details: Array<Record<string, unknown>>
  error_list: Array<{ file: string; error: string }>
}

export interface OptimizerStatus {
  running: boolean
  mode: string
  started_at: number | null
  finished_at: number | null
  progress: { current: number; total: number; file: string }
  last_result: OptimizerRunResult | null
  config: OptimizerConfig
}

const EMPTY_STATUS: OptimizerStatus = {
  running: false,
  mode: 'none',
  started_at: null,
  finished_at: null,
  progress: { current: 0, total: 0, file: '' },
  last_result: null,
  config: { enabled: false, max_width: 1920, max_height: 1080, quality: 90, pic_dir: '' }
}

export const useOptimizerStore = defineStore('optimizer', () => {
  const status = ref<OptimizerStatus>({ ...EMPTY_STATUS })
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchStatus() {
    try {
      const { data } = await api.get<OptimizerStatus>('/optimizer/status')
      status.value = data
      error.value = null
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha na operação do otimizador')
    }
  }

  async function saveConfig(patch: Partial<OptimizerConfig>) {
    loading.value = true
    try {
      const { data } = await api.put<OptimizerConfig>('/optimizer/config', patch)
      status.value = { ...status.value, config: data }
      error.value = null
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha na operação do otimizador')
      throw err
    } finally {
      loading.value = false
    }
  }

  async function run(mode: OptimizerMode) {
    loading.value = true
    try {
      await api.post('/optimizer/run', { mode })
      error.value = null
      await fetchStatus()
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha na operação do otimizador')
      throw err
    } finally {
      loading.value = false
    }
  }

  return { status, loading, error, fetchStatus, saveConfig, run }
})
