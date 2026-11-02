<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon,
  CheckBadgeIcon,
  MagnifyingGlassIcon,
  PhotoIcon,
  PlayIcon
} from '@heroicons/vue/24/outline'
import ActionBar from '../components/ui/ActionBar.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import NumberField from '../components/settings/NumberField.vue'
import ToggleSwitch from '../components/settings/ToggleSwitch.vue'
import { useOptimizerStore, type OptimizerMode } from '../stores/optimizer'

const { t } = useI18n()
const store = useOptimizerStore()

const form = reactive({
  enabled: false,
  max_width: 1920,
  max_height: 1080,
  quality: 90,
  preserve_aspect: true
})
const configDirty = ref(false)
// Box ratio (height / width) kept while "preserve aspect" is on, so adjusting
// the max width recomputes a proportional max height (default 1920x1080 = 16:9).
const lockedRatio = ref(1080 / 1920)
let poller: number | undefined

function clampHeight(value: number): number {
  return Math.max(240, Math.min(4320, Math.round(value)))
}

const status = computed(() => store.status)
const running = computed(() => store.status.running)
const result = computed(() => store.status.last_result)
const progress = computed(() => store.status.progress)
const progressPct = computed(() => {
  const { current, total } = progress.value
  return total > 0 ? Math.round((current / total) * 100) : 0
})

watch(
  () => store.status.config,
  config => {
    if (configDirty.value) return
    form.enabled = config.enabled
    form.max_width = config.max_width
    form.max_height = config.max_height
    form.quality = config.quality
    form.preserve_aspect = config.preserve_aspect
    if (config.max_width > 0) lockedRatio.value = config.max_height / config.max_width
  },
  { immediate: true, deep: true }
)

function markDirty() {
  configDirty.value = true
}

function onWidthChange(value: number) {
  form.max_width = value
  if (form.preserve_aspect) form.max_height = clampHeight(value * lockedRatio.value)
  markDirty()
}

function onHeightChange(value: number) {
  form.max_height = value
  markDirty()
}

function onPreserveChange(value: boolean) {
  form.preserve_aspect = value
  // Re-capture the current box ratio when turning the lock back on.
  if (value && form.max_width > 0) lockedRatio.value = form.max_height / form.max_width
  markDirty()
}

async function saveConfig() {
  await store.saveConfig({
    enabled: form.enabled,
    max_width: form.max_width,
    max_height: form.max_height,
    quality: form.quality,
    preserve_aspect: form.preserve_aspect
  })
  configDirty.value = false
}

async function runMode(mode: OptimizerMode) {
  if (mode === 'apply' && !window.confirm(t('optimizer.confirmApply'))) return
  await store.run(mode)
}

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KiB', 'MiB', 'GiB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

function formatTime(epoch: number | null): string {
  if (!epoch) return '—'
  return new Date(epoch * 1000).toLocaleString()
}

const modeLabel = computed(() => {
  switch (status.value.mode) {
    case 'scan':
      return t('optimizer.modeScan')
    case 'apply':
      return t('optimizer.modeApply')
    case 'verify':
      return t('optimizer.modeVerify')
    default:
      return '—'
  }
})

onMounted(() => {
  void store.fetchStatus()
  poller = window.setInterval(() => void store.fetchStatus(), 1500)
})

onBeforeUnmount(() => {
  if (poller !== undefined) window.clearInterval(poller)
})
</script>

<template>
  <div class="mx-auto max-w-7xl space-y-5 p-4 sm:p-6 lg:p-8">
    <PageHeader :title="t('optimizer.title')" :description="t('optimizer.description')">
      <template #icon>
        <PhotoIcon class="h-8 w-8 text-indigo-500" />
      </template>
      <template #actions>
        <ActionBar>
          <button
            type="button"
            class="inline-flex items-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
            :disabled="running"
            @click="runMode('scan')"
          >
            <MagnifyingGlassIcon class="mr-2 h-4 w-4" />
            {{ t('optimizer.scan') }}
          </button>
          <button
            type="button"
            class="inline-flex items-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
            :disabled="running"
            @click="runMode('verify')"
          >
            <CheckBadgeIcon class="mr-2 h-4 w-4" />
            {{ t('optimizer.verify') }}
          </button>
          <button
            type="button"
            class="inline-flex items-center rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="running"
            @click="runMode('apply')"
          >
            <PlayIcon class="mr-2 h-4 w-4" />
            {{ t('optimizer.apply') }}
          </button>
        </ActionBar>
      </template>
    </PageHeader>

    <div
      v-if="store.error"
      class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
    >
      {{ store.error }}
    </div>

    <!-- Live progress -->
    <section
      v-if="running"
      class="space-y-3 rounded-lg border border-indigo-200 bg-indigo-50 p-4 shadow-sm dark:border-indigo-500/30 dark:bg-indigo-500/10"
    >
      <div class="flex items-center gap-2 text-sm font-semibold text-indigo-800 dark:text-indigo-200">
        <ArrowPathIcon class="h-5 w-5 animate-spin" />
        {{ t('optimizer.running', { mode: modeLabel }) }}
      </div>
      <div class="h-2 w-full overflow-hidden rounded-full bg-indigo-200 dark:bg-indigo-900">
        <div
          class="h-full rounded-full bg-indigo-600 transition-all"
          :style="{ width: `${progressPct}%` }"
        ></div>
      </div>
      <p class="truncate text-xs text-indigo-700 dark:text-indigo-300">
        {{ progress.current }} / {{ progress.total }} — {{ progress.file || '…' }}
      </p>
    </section>

    <!-- Configuration -->
    <section
      class="space-y-5 rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800/90 sm:p-6"
    >
      <div>
        <h2 class="text-lg font-bold text-gray-900 dark:text-white">
          {{ t('optimizer.settings') }}
        </h2>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          {{ t('optimizer.library') }}:
          <span class="font-mono">{{ status.config.pic_dir || '—' }}</span>
        </p>
      </div>

      <div class="flex items-center justify-between gap-4">
        <div>
          <p class="text-sm font-medium text-gray-900 dark:text-gray-100">
            {{ t('optimizer.autoEnabled') }}
          </p>
          <p class="text-xs text-gray-500 dark:text-gray-400">
            {{ t('optimizer.autoEnabledHelp') }}
          </p>
        </div>
        <ToggleSwitch
          :model-value="form.enabled"
          :label="t('optimizer.autoEnabled')"
          @update:model-value="
            value => {
              form.enabled = value
              markDirty()
            }
          "
        />
      </div>

      <div class="flex items-start justify-between gap-4">
        <div>
          <p class="text-sm font-medium text-gray-900 dark:text-gray-100">
            {{ t('optimizer.preserveAspect') }}
          </p>
          <p class="text-xs text-gray-500 dark:text-gray-400">
            {{ t('optimizer.preserveAspectHelp') }}
          </p>
        </div>
        <ToggleSwitch
          :model-value="form.preserve_aspect"
          :label="t('optimizer.preserveAspect')"
          @update:model-value="onPreserveChange"
        />
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <label class="space-y-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">
            {{ t('optimizer.maxWidth') }}
          </span>
          <NumberField
            :model-value="form.max_width"
            :min="320"
            :max="7680"
            :step="10"
            unit="px"
            @update:model-value="onWidthChange"
          />
        </label>
        <label class="space-y-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">
            {{ t('optimizer.maxHeight') }}
          </span>
          <!-- Locked: height is derived from width; editable only when the user
               opts into independent sizing. -->
          <div
            v-if="form.preserve_aspect"
            class="flex h-10 items-center justify-between rounded-lg border border-dashed border-gray-300 bg-gray-50 px-3 text-sm text-gray-600 dark:border-gray-600 dark:bg-gray-900/40 dark:text-gray-300"
            :title="t('optimizer.maxHeightDerived')"
          >
            <span class="font-mono">{{ form.max_height }} px</span>
            <span class="text-xs text-gray-400 dark:text-gray-500">{{ t('optimizer.auto') }}</span>
          </div>
          <NumberField
            v-else
            :model-value="form.max_height"
            :min="240"
            :max="4320"
            :step="10"
            unit="px"
            @update:model-value="onHeightChange"
          />
        </label>
        <label class="space-y-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">
            {{ t('optimizer.quality') }}
          </span>
          <NumberField
            :model-value="form.quality"
            :min="40"
            :max="100"
            :step="1"
            @update:model-value="
              value => {
                form.quality = value
                markDirty()
              }
            "
          />
        </label>
      </div>

      <div
        v-if="!form.preserve_aspect"
        class="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
      >
        <span>⚠️</span>
        <span>{{ t('optimizer.distortionWarning') }}</span>
      </div>

      <div class="flex items-center gap-3">
        <button
          type="button"
          class="inline-flex items-center rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="!configDirty || store.loading"
          @click="saveConfig"
        >
          {{ t('optimizer.save') }}
        </button>
        <span v-if="configDirty" class="text-xs text-amber-600 dark:text-amber-400">
          {{ t('optimizer.unsaved') }}
        </span>
      </div>
    </section>

    <!-- Last result -->
    <section
      v-if="result"
      class="space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800/90 sm:p-6"
    >
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-lg font-bold text-gray-900 dark:text-white">
          {{ t('optimizer.lastRun') }}
        </h2>
        <span
          :class="[
            'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold',
            result.ok
              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
              : 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300'
          ]"
        >
          {{ result.ok ? t('optimizer.ok') : t('optimizer.withErrors') }} · {{ modeLabel }} ·
          {{ formatTime(status.finished_at) }}
        </span>
      </div>

      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div class="rounded-lg bg-gray-50 p-3 dark:bg-gray-900/50">
          <p class="text-2xl font-bold text-gray-900 dark:text-white">{{ result.analyzed }}</p>
          <p class="text-xs text-gray-500 dark:text-gray-400">{{ t('optimizer.analyzed') }}</p>
        </div>
        <div class="rounded-lg bg-gray-50 p-3 dark:bg-gray-900/50">
          <p class="text-2xl font-bold text-indigo-600 dark:text-indigo-400">
            {{ result.resized }}
          </p>
          <p class="text-xs text-gray-500 dark:text-gray-400">{{ t('optimizer.resized') }}</p>
        </div>
        <div class="rounded-lg bg-gray-50 p-3 dark:bg-gray-900/50">
          <p class="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
            {{ result.already_ok }}
          </p>
          <p class="text-xs text-gray-500 dark:text-gray-400">{{ t('optimizer.alreadyOk') }}</p>
        </div>
        <div class="rounded-lg bg-gray-50 p-3 dark:bg-gray-900/50">
          <p
            :class="[
              'text-2xl font-bold',
              result.errors ? 'text-red-600 dark:text-red-400' : 'text-gray-900 dark:text-white'
            ]"
          >
            {{ result.errors }}
          </p>
          <p class="text-xs text-gray-500 dark:text-gray-400">{{ t('optimizer.errors') }}</p>
        </div>
        <div class="rounded-lg bg-gray-50 p-3 dark:bg-gray-900/50">
          <p class="text-2xl font-bold text-gray-900 dark:text-white">
            {{ formatBytes(result.bytes_saved) }}
          </p>
          <p class="text-xs text-gray-500 dark:text-gray-400">{{ t('optimizer.spaceSaved') }}</p>
        </div>
        <div class="rounded-lg bg-gray-50 p-3 dark:bg-gray-900/50">
          <p class="text-2xl font-bold text-gray-900 dark:text-white">
            {{ result.duration_s }}s
          </p>
          <p class="text-xs text-gray-500 dark:text-gray-400">{{ t('optimizer.duration') }}</p>
        </div>
      </div>

      <div v-if="result.error_list.length" class="space-y-1">
        <h3 class="text-sm font-semibold text-red-700 dark:text-red-300">
          {{ t('optimizer.errorDetails') }}
        </h3>
        <ul class="space-y-1 text-xs text-red-600 dark:text-red-400">
          <li v-for="(item, index) in result.error_list" :key="index" class="font-mono">
            {{ item.file }}: {{ item.error }}
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>
