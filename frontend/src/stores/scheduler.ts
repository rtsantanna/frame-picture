import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'
import { getApiErrorMessage } from '../utils/errors'

const api = axios.create({
  baseURL: import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
})

export interface ScheduleState {
  enabled?: boolean
  cron?: string
  command?: string
  next_run?: string | null
  error?: string | null
  applied_at?: number
  presets?: Record<string, string>
  last_sync?: Record<string, unknown>
}

export const FREQS: Array<{ id: string; label: string }> = [
  { id: '5m', label: '5 minutos' },
  { id: '10m', label: '10 minutos' },
  { id: '15m', label: '15 minutos' },
  { id: '30m', label: '30 minutos' },
  { id: '1h', label: '1 hora' },
  { id: '2h', label: '2 horas' },
  { id: '6h', label: '6 horas' },
  { id: '12h', label: '12 horas' },
  { id: '24h', label: '24 horas' }
]

export const useSchedulerStore = defineStore('scheduler', () => {
  const state = ref<ScheduleState>({})
  const sync = ref<Record<string, unknown>>({ running: false, result: 'unknown' })
  const divergences = ref<Array<Record<string, unknown>>>([])
  const error = ref<string | null>(null)

  async function fetchSchedule() {
    try {
      const { data } = await api.get<ScheduleState>('/scheduler/dropbox')
      state.value = data
      if (data.last_sync) sync.value = data.last_sync as Record<string, unknown>
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha ao ler o agendamento')
    }
  }
  async function saveSchedule(patch: { enabled?: boolean; frequency?: string }) {
    try {
      await api.put('/scheduler/dropbox', patch)
      error.value = null
      // give the host path-unit a moment, then re-read
      await new Promise(r => setTimeout(r, 1500))
      await fetchSchedule()
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha ao salvar o agendamento')
      throw err
    }
  }
  async function fetchSync() {
    try {
      const { data } = await api.get('/sync/status')
      sync.value = data
    } catch { /* ignore */ }
  }
  async function syncNow() {
    const { data } = await api.post('/sync/now')
    await fetchSync()
    return data
  }
  async function fetchDivergences() {
    try {
      const { data } = await api.get('/sync/divergences')
      divergences.value = Array.isArray(data.items) ? data.items : []
    } catch { /* ignore */ }
  }
  async function resolveDivergence(path: string) {
    const { data } = await api.post('/sync/divergence/resolve', { path })
    await fetchDivergences()
    return data
  }

  return {
    state, sync, divergences, error,
    fetchSchedule, saveSchedule, fetchSync, syncNow, fetchDivergences, resolveDivergence
  }
})
