import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
})

export const useMonitorStore = defineStore('monitor', () => {
  const metrics = ref<Record<string, any>>({})
  const diagnostics = ref<Record<string, any>>({})
  const updatedAt = ref<number | null>(null)
  const error = ref<string | null>(null)

  async function fetchMetrics() {
    try {
      const { data } = await api.get('/system/monitor')
      metrics.value = data
      updatedAt.value = Date.now()
      error.value = null
    } catch {
      error.value = 'Métricas indisponíveis'
    }
  }
  async function fetchDiagnostics() {
    try {
      const { data } = await api.get('/system/diagnostics')
      diagnostics.value = data
    } catch {
      error.value = 'Diagnóstico indisponível'
    }
  }

  return { metrics, diagnostics, updatedAt, error, fetchMetrics, fetchDiagnostics }
})
