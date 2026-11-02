<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import ToggleSwitch from '../components/settings/ToggleSwitch.vue'
import { useNightStore } from '../stores/night'

const store = useNightStore()
const form = reactive({ enabled: false, off_time: '00:00', on_time: '06:00' })
const dirty = ref(false)
let poller: number | undefined

watch(
  () => store.settings,
  s => {
    if (dirty.value) return
    form.enabled = s.enabled
    form.off_time = s.off_time
    form.on_time = s.on_time
  },
  { deep: true, immediate: true }
)

onMounted(() => {
  store.fetch()
  poller = window.setInterval(() => { if (!dirty.value) store.fetch() }, 5000)
})
onBeforeUnmount(() => { if (poller) window.clearInterval(poller) })

async function save() {
  await store.save({ enabled: form.enabled, off_time: form.off_time, on_time: form.on_time })
  dirty.value = false
}
function fmt(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('pt-BR', { weekday: 'short', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-5 p-4 sm:p-6">
    <div>
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Agendador noturno</h1>
      <p class="text-sm text-gray-500 dark:text-gray-400">
        Coloca a tela (HDMI) em standby à noite e pausa a apresentação. Não desliga o Raspberry
        nem o Docker. Fuso: {{ store.settings.timezone }}.
      </p>
    </div>

    <div v-if="store.error" class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
      {{ store.error }}
    </div>

    <!-- Status -->
    <section class="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <div class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
        <p class="text-xs text-gray-500 dark:text-gray-400">Agendador</p>
        <p class="text-lg font-bold" :class="store.settings.enabled ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-400'">
          {{ store.settings.enabled ? 'Ativo' : 'Inativo' }}
        </p>
      </div>
      <div class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
        <p class="text-xs text-gray-500 dark:text-gray-400">Tela (HDMI)</p>
        <p class="text-lg font-bold" :class="store.settings.hdmi_on ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'">
          {{ store.settings.hdmi_on ? 'Ligada' : 'Em standby' }}
        </p>
      </div>
      <div class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
        <p class="text-xs text-gray-500 dark:text-gray-400">Exceção desta noite</p>
        <p class="text-lg font-bold" :class="store.settings.exception_active ? 'text-amber-600 dark:text-amber-400' : 'text-gray-400'">
          {{ store.settings.exception_active ? 'Ativa' : 'Inativa' }}
        </p>
      </div>
      <div class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
        <p class="text-xs text-gray-500 dark:text-gray-400">Próximo desligamento</p>
        <p class="text-sm font-semibold text-gray-900 dark:text-white">{{ fmt(store.settings.next_off) }}</p>
      </div>
      <div class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
        <p class="text-xs text-gray-500 dark:text-gray-400">Próximo despertar</p>
        <p class="text-sm font-semibold text-gray-900 dark:text-white">{{ fmt(store.settings.next_on) }}</p>
      </div>
    </section>

    <!-- Settings -->
    <section class="space-y-5 rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
      <div class="flex items-center justify-between">
        <div>
          <p class="text-sm font-medium text-gray-900 dark:text-gray-100">Habilitar agendamento</p>
          <p class="text-xs text-gray-500 dark:text-gray-400">Desliga a tela no horário e religa de manhã.</p>
        </div>
        <ToggleSwitch :model-value="form.enabled" label="Habilitar agendamento"
          @update:model-value="v => { form.enabled = v; dirty = true }" />
      </div>
      <div class="grid grid-cols-2 gap-4">
        <label class="space-y-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Desligar às</span>
          <input :value="form.off_time" type="time"
            class="block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
            @input="e => { form.off_time = (e.target as HTMLInputElement).value; dirty = true }" />
        </label>
        <label class="space-y-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Religar às</span>
          <input :value="form.on_time" type="time"
            class="block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
            @input="e => { form.on_time = (e.target as HTMLInputElement).value; dirty = true }" />
        </label>
      </div>
      <div class="flex items-center gap-3">
        <button type="button" class="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
          :disabled="!dirty || store.loading" @click="save">Salvar</button>
        <span v-if="dirty" class="text-xs text-amber-600 dark:text-amber-400">Alterações não salvas</span>
      </div>
    </section>

    <!-- Exception -->
    <section class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
      <div>
        <p class="text-sm font-semibold text-amber-800 dark:text-amber-200">Manter monitor ligado esta noite</p>
        <p class="text-xs text-amber-700 dark:text-amber-300">
          Vale só para a próxima janela noturna, sobrevive a reinício e expira sozinha.
        </p>
      </div>
      <div class="flex gap-2">
        <button v-if="!store.settings.exception_active" type="button"
          class="rounded-lg bg-amber-600 px-3 py-2 text-sm font-semibold text-white hover:bg-amber-700"
          @click="store.keepOnTonight(true)">Manter ligado</button>
        <button v-else type="button"
          class="rounded-lg bg-gray-600 px-3 py-2 text-sm font-semibold text-white hover:bg-gray-700"
          @click="store.keepOnTonight(false)">Cancelar exceção</button>
      </div>
    </section>
  </div>
</template>
