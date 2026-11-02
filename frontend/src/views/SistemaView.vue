<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import LogsView from './LogsView.vue'
import { useMonitorStore } from '../stores/monitor'

const store = useMonitorStore()
const tab = ref<'mon' | 'logs' | 'diag'>('mon')
let poll: number | undefined

onMounted(() => {
  store.fetchMetrics()
  store.fetchDiagnostics()
  poll = window.setInterval(() => { if (tab.value === 'mon') store.fetchMetrics() }, 5000)
})
onBeforeUnmount(() => { if (poll) window.clearInterval(poll) })

function gb(bytes: unknown): string {
  const n = Number(bytes)
  if (!n && n !== 0) return 'Indisponível'
  if (!Number.isFinite(n)) return 'Indisponível'
  return (n / 1024 ** 3).toFixed(1) + ' GB'
}
function pct(v: unknown): string {
  return v === null || v === undefined ? 'Indisponível' : `${v}%`
}
function dur(s: unknown): string {
  const n = Number(s)
  if (!n) return '—'
  const d = Math.floor(n / 86400), h = Math.floor((n % 86400) / 3600), m = Math.floor((n % 3600) / 60)
  return (d ? `${d}d ` : '') + `${h}h ${m}m`
}
const host = computed(() => store.metrics.host ?? {})
const cont = computed(() => store.metrics.container ?? {})
const disk = computed(() => host.value.disk ?? {})
</script>

<template>
  <div class="mx-auto max-w-4xl p-4 sm:p-6">
    <h1 class="mb-1 text-2xl font-bold text-gray-900 dark:text-white">Sistema</h1>
    <p class="mb-4 text-sm text-gray-500 dark:text-gray-400">Monitoramento, logs e diagnóstico do Frame Picture.</p>

    <div class="mb-5 flex gap-1 border-b border-gray-200 dark:border-gray-700">
      <button v-for="t in [['mon','Monitoramento'],['logs','Logs'],['diag','Diagnóstico']]" :key="t[0]" type="button"
        class="px-4 py-2 text-sm font-medium"
        :class="tab === t[0] ? 'border-b-2 border-indigo-600 text-indigo-600 dark:text-indigo-400' : 'text-gray-500'"
        @click="tab = (t[0] as any)">{{ t[1] }}</button>
    </div>

    <!-- Monitoramento -->
    <div v-show="tab === 'mon'" class="space-y-5">
      <p class="text-xs text-gray-400">Atualizado: {{ store.updatedAt ? new Date(store.updatedAt).toLocaleTimeString('pt-BR') : '—' }} (a cada 5s)</p>
      <div>
        <h2 class="mb-2 text-sm font-semibold text-gray-700 dark:text-gray-300">Raspberry Pi</h2>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <div v-for="c in [
            { l: 'CPU', v: pct(host.cpu_percent) },
            { l: 'RAM usada', v: gb(host.mem_used) + ' / ' + gb(host.mem_total) },
            { l: 'RAM livre', v: gb(host.mem_available) },
            { l: 'Swap usado', v: gb(host.swap_used) },
            { l: 'Temperatura', v: host.temp_c != null ? host.temp_c + ' °C' : 'Indisponível' },
            { l: 'Load avg', v: host.loadavg ? host.loadavg.join(' / ') : 'Indisponível' },
            { l: 'Uptime', v: dur(host.uptime_s) },
            { l: 'Disco', v: gb(disk.used) + ' / ' + gb(disk.total) }
          ]" :key="c.l" class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
            <p class="text-lg font-bold text-gray-900 dark:text-white">{{ c.v }}</p>
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ c.l }}</p>
          </div>
        </div>
      </div>
      <div>
        <h2 class="mb-2 text-sm font-semibold text-gray-700 dark:text-gray-300">Container Frame Picture</h2>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div v-for="c in [
            { l: 'CPU container', v: pct(cont.cpu_percent) },
            { l: 'RAM container', v: gb(cont.mem_used) },
            { l: 'Tela (HDMI)', v: store.metrics.hdmi_on === true ? 'Ligada' : store.metrics.hdmi_on === false ? 'Standby' : 'Indisponível' },
            { l: 'Agendador noturno', v: store.metrics.night ? (store.metrics.night.enabled ? 'Ativo' : 'Inativo') : 'Indisponível' }
          ]" :key="c.l" class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
            <p class="text-lg font-bold text-gray-900 dark:text-white">{{ c.v }}</p>
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ c.l }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Logs -->
    <div v-show="tab === 'logs'"><LogsView /></div>

    <!-- Diagnóstico -->
    <div v-show="tab === 'diag'" class="rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
      <dl class="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <div v-for="(v, k) in store.diagnostics" :key="k" class="flex justify-between gap-2 border-b border-gray-100 py-1 dark:border-gray-700/60">
          <dt class="text-gray-500 dark:text-gray-400">{{ k }}</dt>
          <dd class="truncate text-right font-mono text-gray-900 dark:text-gray-200" :title="String(v)">{{ v ?? 'Indisponível' }}</dd>
        </div>
      </dl>
    </div>
  </div>
</template>
