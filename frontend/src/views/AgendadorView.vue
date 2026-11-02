<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import NightView from './NightView.vue'
import { useSchedulerStore, FREQS } from '../stores/scheduler'

const store = useSchedulerStore()
const tab = ref<'noturno' | 'dropbox'>('noturno')

const enabled = ref(true)
const frequency = ref('10m')
const dirty = ref(false)
let poll: number | undefined

const syncing = computed(() => (store.sync as Record<string, unknown>).running === true)

function freqFromCron(cron?: string): string {
  const hit = FREQS.find(f => {
    const map: Record<string, string> = {
      '5m': '*/5 * * * *', '10m': '*/10 * * * *', '15m': '*/15 * * * *',
      '30m': '*/30 * * * *', '1h': '0 * * * *', '2h': '0 */2 * * *',
      '6h': '0 */6 * * *', '12h': '0 */12 * * *', '24h': '0 0 * * *'
    }
    return map[f.id] === cron
  })
  return hit ? hit.id : '10m'
}

async function reload() {
  await store.fetchSchedule()
  if (!dirty.value) {
    enabled.value = store.state.enabled !== false
    frequency.value = freqFromCron(store.state.cron)
  }
}

onMounted(() => {
  reload()
  store.fetchSync()
  store.fetchDivergences()
  poll = window.setInterval(() => { store.fetchSync(); if (!dirty.value) store.fetchSchedule() }, 5000)
})
onBeforeUnmount(() => { if (poll) window.clearInterval(poll) })

async function save() {
  await store.saveSchedule({ enabled: enabled.value, frequency: frequency.value })
  dirty.value = false
}
async function syncNow() {
  await store.syncNow()
  const started = Date.now()
  const p = window.setInterval(async () => {
    await store.fetchSync()
    if (!syncing.value || Date.now() - started > 120000) {
      window.clearInterval(p)
      await store.fetchDivergences()
    }
  }, 3000)
}
async function resolve(path: string) {
  if (!window.confirm(`Atualizar a cópia local de "${path}" com a versão do Dropbox?`)) return
  await store.resolveDivergence(path)
}
function fmtEpoch(v: unknown): string {
  const n = Number(v)
  return n ? new Date(n * 1000).toLocaleString('pt-BR') : '—'
}
function fmtIso(v?: string | null): string {
  if (!v) return '—'
  try { return new Date(v).toLocaleString('pt-BR') } catch { return v }
}
</script>

<template>
  <div class="mx-auto max-w-4xl p-4 sm:p-6">
    <h1 class="mb-1 text-2xl font-bold text-gray-900 dark:text-white">Agendador</h1>
    <p class="mb-4 text-sm text-gray-500 dark:text-gray-400">Standby noturno da tela e sincronização do Dropbox.</p>

    <div class="mb-5 flex gap-1 border-b border-gray-200 dark:border-gray-700">
      <button type="button" class="px-4 py-2 text-sm font-medium"
        :class="tab === 'noturno' ? 'border-b-2 border-indigo-600 text-indigo-600 dark:text-indigo-400' : 'text-gray-500'"
        @click="tab = 'noturno'">Noturno</button>
      <button type="button" class="px-4 py-2 text-sm font-medium"
        :class="tab === 'dropbox' ? 'border-b-2 border-indigo-600 text-indigo-600 dark:text-indigo-400' : 'text-gray-500'"
        @click="tab = 'dropbox'">Dropbox</button>
    </div>

    <NightView v-show="tab === 'noturno'" />

    <div v-show="tab === 'dropbox'" class="space-y-5">
      <div v-if="store.error" class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">{{ store.error }}</div>

      <!-- Sincronização automática (crontab real) -->
      <section class="space-y-4 rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
        <h2 class="text-lg font-bold text-gray-900 dark:text-white">Sincronização automática</h2>
        <div class="flex items-center justify-between">
          <span class="text-sm text-gray-700 dark:text-gray-300">Habilitar agendamento</span>
          <input type="checkbox" :checked="enabled" @change="enabled = ($event.target as HTMLInputElement).checked; dirty = true" />
        </div>
        <label class="block space-y-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Frequência</span>
          <select :value="frequency" :disabled="!enabled"
            class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
            @change="frequency = ($event.target as HTMLSelectElement).value; dirty = true">
            <option v-for="f in FREQS" :key="f.id" :value="f.id">{{ f.label }}</option>
          </select>
        </label>
        <div class="grid grid-cols-1 gap-2 rounded-lg bg-gray-50 p-3 text-xs text-gray-600 dark:bg-gray-900/40 dark:text-gray-300 sm:grid-cols-2">
          <div>Expressão cron aplicada: <b class="font-mono">{{ store.state.cron ?? '—' }}</b></div>
          <div>Próxima execução: <b>{{ fmtIso(store.state.next_run) }}</b></div>
          <div>Última sincronização: <b>{{ fmtEpoch((store.sync as any).last_sync_epoch) }}</b></div>
          <div>Status: <b>{{ (store.sync as any).result ?? '—' }}</b></div>
        </div>
        <div v-if="store.state.error" class="text-xs text-red-600">Erro: {{ store.state.error }}</div>
        <button type="button" class="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
          :disabled="!dirty" @click="save">Salvar configuração</button>
      </section>

      <!-- Sincronizar agora -->
      <section class="space-y-3 rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
        <h2 class="text-lg font-bold text-gray-900 dark:text-white">Sincronização manual</h2>
        <div class="flex flex-wrap items-center gap-3">
          <button type="button" class="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:opacity-60"
            :disabled="syncing" @click="syncNow">{{ syncing ? 'Sincronizando…' : 'Sincronizar agora' }}</button>
          <span class="text-xs text-gray-500 dark:text-gray-400">
            {{ syncing ? 'Executando…' : ((store.sync as any).result === 'ok' ? 'Concluído' : (store.sync as any).result === 'error' ? 'Falhou' : '—') }}
            · início {{ fmtEpoch((store.sync as any).last_sync_epoch) }}
            · {{ (store.sync as any).duration_s ?? 0 }}s
            · novos {{ (store.sync as any).new_files ?? 0 }}
            · erros {{ (store.sync as any).errors ?? 0 }}
          </span>
        </div>
      </section>

      <!-- Divergências -->
      <section class="space-y-3 rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
        <h2 class="text-lg font-bold text-gray-900 dark:text-white">Divergências Dropbox ({{ store.divergences.length }})</h2>
        <p v-if="!store.divergences.length" class="text-sm text-gray-400">Nenhuma divergência.</p>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="text-gray-400"><tr><th class="p-1">Arquivo</th><th class="p-1">Situação</th><th class="p-1">Detectado</th><th class="p-1">Ação</th></tr></thead>
            <tbody>
              <tr v-for="(d, i) in store.divergences" :key="i" class="border-t border-gray-100 dark:border-gray-700/60">
                <td class="p-1 font-mono">{{ (d as any).path }}</td>
                <td class="p-1"><span class="rounded-full bg-amber-100 px-2 py-0.5 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">{{ (d as any).status === 'updated_source' ? 'Atualizado na origem' : (d as any).status === 'absent_source' ? 'Ausente na origem' : (d as any).status }}</span></td>
                <td class="p-1">{{ fmtEpoch((d as any).detected_at) }}</td>
                <td class="p-1">
                  <button v-if="(d as any).status === 'updated_source'" type="button" class="rounded bg-indigo-600 px-2 py-1 text-[11px] text-white hover:bg-indigo-700" @click="resolve((d as any).path)">Atualizar cópia local</button>
                  <span v-else class="text-gray-400">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="text-[11px] text-gray-400">Divergências não sobrescrevem a cópia local automaticamente.</p>
      </section>
    </div>
  </div>
</template>
