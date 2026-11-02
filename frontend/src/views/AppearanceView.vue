<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { AdjustmentsHorizontalIcon, ArrowPathIcon, CheckIcon } from '@heroicons/vue/24/outline'
import { useConfigStore } from '../stores/config'
import { usePlayerStore } from '../stores/player'
import { useAppearanceStore, type OverlayAppearance } from '../stores/appearance'
import TextOverlayControls from '../components/TextOverlayControls.vue'
import OverlayAppearanceSection from '../components/OverlayAppearanceSection.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import FieldRow from '../components/settings/FieldRow.vue'
import NumberField from '../components/settings/NumberField.vue'
import ToggleSwitch from '../components/settings/ToggleSwitch.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import Panel from '../components/ui/Panel.vue'
import StatusBanner from '../components/ui/StatusBanner.vue'

const { t } = useI18n()
const configStore = useConfigStore()
const playerStore = usePlayerStore()
const { config, isLoading: isConfigLoading, error: configError } = storeToRefs(configStore)

const appearance = reactive({
  time_delay: 200,
  fade_time: 10,
  portrait_pairs: false
})

const isSaving = ref(false)
const statusMessage = ref('')
const statusTone = ref<'success' | 'danger'>('success')
let statusTimer: number | undefined

const unavailableMessage = computed(() => {
  if (!configError.value) return t('appearance.unavailable')
  return t('appearance.unavailableWithDetail', { detail: configError.value })
})

// The touch overlay appearance controls only apply when the master overlay
// toggle (managed in Settings) is on. The overlay renderer starts only at
// service startup, so this gate reads the live `overlay.enabled` from the
// shared config blob (populated by the workflow-config allowlist).
const overlayEnabled = computed(() => config.value?.overlay?.enabled === true)

const asNumber = (value: unknown, fallback: number) => {
  const nextValue = Number(value)
  return Number.isFinite(nextValue) ? nextValue : fallback
}

const syncFromConfig = () => {
  const model = config.value?.model || {}
  appearance.time_delay = asNumber(model.time_delay, 200)
  appearance.fade_time = asNumber(model.fade_time, 10)
  appearance.portrait_pairs = Boolean(model.portrait_pairs)
}

const showStatus = (tone: 'success' | 'danger', message: string) => {
  if (statusTimer !== undefined) {
    window.clearTimeout(statusTimer)
  }
  statusTone.value = tone
  statusMessage.value = message
  statusTimer = window.setTimeout(() => {
    statusMessage.value = ''
  }, 3000)
}

const loadAppearance = async () => {
  statusMessage.value = ''
  await configStore.fetchWorkflowConfig()
  syncFromConfig()
}

const saveAppearance = async () => {
  if (isSaving.value) return
  isSaving.value = true
  statusMessage.value = ''

  try {
    await configStore.saveWorkflowConfig({
      model: {
        time_delay: Number(appearance.time_delay),
        fade_time: Number(appearance.fade_time),
        portrait_pairs: Boolean(appearance.portrait_pairs)
      }
    })
    playerStore.sendCommand('REQUEST_STATE')
    showStatus('success', t('appearance.saved'))
  } catch (error) {
    console.error(error)
    showStatus('danger', t('appearance.failed'))
  } finally {
    isSaving.value = false
  }
}

onMounted(() => {
  void loadAppearance()
})

onBeforeUnmount(() => {
  if (statusTimer !== undefined) {
    window.clearTimeout(statusTimer)
  }
})

watch(
  () => [
    config.value?.model?.time_delay,
    config.value?.model?.fade_time,
    config.value?.model?.portrait_pairs
  ],
  () => {
    if (!isSaving.value) {
      syncFromConfig()
    }
  },
  { immediate: true }
)

const appearanceStore = useAppearanceStore()
const hdmi = computed(() => appearanceStore.state)
async function saveHdmi(patch: Partial<OverlayAppearance>) {
  try { await appearanceStore.save(patch) } catch { /* surfaced via store */ }
}
onMounted(() => appearanceStore.fetch())
</script>

<template>
  <div class="space-y-6">
    <PageHeader :title="t('appearance.title')" :description="t('appearance.description')">
      <template #icon>
        <div
          class="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-lg bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300"
        >
          <AdjustmentsHorizontalIcon class="h-6 w-6" />
        </div>
      </template>
    </PageHeader>

    <!-- Aparência dos textos na HDMI (Missao 06) -->
    <Panel padded>
      <div class="mb-4">
        <h2 class="text-lg font-semibold text-gray-950 dark:text-white">Aparência dos textos na HDMI</h2>
        <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">
          Descrição e data (canto inferior esquerdo) e relógio (canto inferior direito). Aplica ao vivo, sem reiniciar.
        </p>
      </div>
      <div class="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <!-- Descrição -->
        <div class="space-y-2 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
          <div class="flex items-center justify-between">
            <span class="text-sm font-semibold text-gray-900 dark:text-white">Descrição</span>
            <input type="checkbox" :checked="hdmi.description_enabled" @change="saveHdmi({ description_enabled: ($event.target as HTMLInputElement).checked })" />
          </div>
          <p class="text-[11px] text-gray-400">Cor/tamanho/fundo são compartilhados com a Data (mesma linha).</p>
        </div>
        <!-- Data -->
        <div class="space-y-2 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
          <div class="flex items-center justify-between">
            <span class="text-sm font-semibold text-gray-900 dark:text-white">Data original</span>
            <input type="checkbox" :checked="hdmi.date_enabled" @change="saveHdmi({ date_enabled: ($event.target as HTMLInputElement).checked })" />
          </div>
          <label class="flex items-center justify-between text-sm">Cor do texto
            <input type="color" :value="hdmi.text_color" @input="saveHdmi({ text_color: ($event.target as HTMLInputElement).value })" /></label>
          <label class="flex items-center justify-between text-sm">Tamanho
            <input type="number" min="8" max="200" :value="hdmi.text_size" class="w-20 rounded border px-2 py-1 text-sm dark:bg-gray-700" @change="saveHdmi({ text_size: Number(($event.target as HTMLInputElement).value) })" /></label>
          <label class="flex items-center justify-between text-sm">Opacidade
            <input type="number" min="0" max="1" step="0.1" :value="hdmi.text_opacity" class="w-20 rounded border px-2 py-1 text-sm dark:bg-gray-700" @change="saveHdmi({ text_opacity: Number(($event.target as HTMLInputElement).value) })" /></label>
          <label class="flex items-center justify-between text-sm">Cor do fundo
            <input type="color" :value="hdmi.text_bg_color" @input="saveHdmi({ text_bg_color: ($event.target as HTMLInputElement).value })" /></label>
          <label class="flex items-center justify-between text-sm">Opacidade do fundo
            <input type="number" min="0" max="1" step="0.05" :value="hdmi.text_bg_opacity" class="w-20 rounded border px-2 py-1 text-sm dark:bg-gray-700" @change="saveHdmi({ text_bg_opacity: Number(($event.target as HTMLInputElement).value) })" /></label>
        </div>
        <!-- Relógio -->
        <div class="space-y-2 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
          <div class="flex items-center justify-between">
            <span class="text-sm font-semibold text-gray-900 dark:text-white">Relógio</span>
            <input type="checkbox" :checked="hdmi.clock_enabled" @change="saveHdmi({ clock_enabled: ($event.target as HTMLInputElement).checked })" />
          </div>
          <label class="flex items-center justify-between text-sm">Cor
            <input type="color" :value="hdmi.clock_color" @input="saveHdmi({ clock_color: ($event.target as HTMLInputElement).value })" /></label>
          <label class="flex items-center justify-between text-sm">Tamanho
            <input type="number" min="8" max="400" :value="hdmi.clock_size" class="w-20 rounded border px-2 py-1 text-sm dark:bg-gray-700" @change="saveHdmi({ clock_size: Number(($event.target as HTMLInputElement).value) })" /></label>
          <label class="flex items-center justify-between text-sm">Opacidade
            <input type="number" min="0" max="1" step="0.1" :value="hdmi.clock_opacity" class="w-20 rounded border px-2 py-1 text-sm dark:bg-gray-700" @change="saveHdmi({ clock_opacity: Number(($event.target as HTMLInputElement).value) })" /></label>
        </div>
      </div>
    </Panel>

    <StatusBanner
      v-if="configError"
      tone="danger"
      :title="t('appearance.unavailableTitle')"
      :message="unavailableMessage"
    >
      <template #actions>
        <button
          type="button"
          class="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 shadow-sm hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500/60 dark:border-red-500/30 dark:bg-gray-900 dark:text-red-200 dark:hover:bg-red-500/10"
          @click="loadAppearance"
        >
          <ArrowPathIcon class="h-4 w-4" />
          {{ t('common.retry') }}
        </button>
      </template>
    </StatusBanner>

    <Panel padded>
      <form class="space-y-6" @submit.prevent="saveAppearance">
        <div class="border-b border-gray-100 pb-5 dark:border-gray-700/60">
          <h2 class="text-lg font-semibold text-gray-950 dark:text-white">
            {{ t('appearance.slideshow.title') }}
          </h2>
          <p class="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-300">
            {{ t('appearance.slideshow.description') }}
          </p>
        </div>

        <div class="space-y-5">
          <FieldRow :label="t('appearance.timeDelay.label')" :help="t('appearance.timeDelay.help')">
            <NumberField v-model="appearance.time_delay" :min="1" :step="1" unit="s" />
          </FieldRow>

          <FieldRow :label="t('appearance.fadeTime.label')" :help="t('appearance.fadeTime.help')">
            <NumberField v-model="appearance.fade_time" :min="0" :step="0.5" unit="s" />
          </FieldRow>

          <FieldRow
            :label="t('appearance.portraitPairs.label')"
            :help="t('appearance.portraitPairs.help')"
          >
            <ToggleSwitch v-model="appearance.portrait_pairs" />
          </FieldRow>
        </div>

        <div
          class="flex flex-col gap-3 border-t border-gray-100 pt-5 dark:border-gray-700/60 sm:flex-row sm:items-center sm:justify-between"
        >
          <div v-if="statusMessage" class="min-w-0 sm:flex-1">
            <StatusBanner :tone="statusTone" :message="statusMessage" />
          </div>
          <div v-else class="hidden sm:block"></div>

          <button
            type="submit"
            :disabled="isSaving || isConfigLoading"
            class="inline-flex items-center justify-center gap-2 rounded-lg bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-500/60 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <CheckIcon class="h-4 w-4" />
            {{ isSaving ? t('appearance.saving') : t('appearance.save') }}
          </button>
        </div>
      </form>
    </Panel>

    <TextOverlayControls />

    <OverlayAppearanceSection v-if="overlayEnabled" />
    <EmptyState
      v-else
      :title="t('appearance.overlay.disabledTitle')"
      :message="t('appearance.overlay.disabledMessage')"
    />
  </div>
</template>
