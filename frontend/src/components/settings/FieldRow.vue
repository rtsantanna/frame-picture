<script setup lang="ts">
import { computed, provide } from 'vue'

const props = defineProps<{
  label: string
  help?: string
  /** Full-width control under the label (list/path/rule editors). */
  wide?: boolean
}>()

const fieldId = computed(() => `field-${props.label.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`)
const labelId = computed(() => `${fieldId.value}-label`)
const helpId = computed(() => `${fieldId.value}-help`)

provide('fieldLabelId', labelId)
provide(
  'fieldHelpId',
  computed(() => (props.help ? helpId.value : undefined))
)
</script>

<template>
  <div
    :class="[
      'grid grid-cols-1 gap-x-8 gap-y-2 border-b border-gray-100 py-3 first:pt-0 last:border-0 last:pb-0 dark:border-gray-700/60',
      wide ? '' : 'md:grid-cols-[minmax(0,1fr)_minmax(11rem,22rem)] md:items-center'
    ]"
  >
    <div class="min-w-0">
      <div :id="labelId" class="block text-sm font-semibold text-gray-900 dark:text-white">
        {{ label }}
      </div>
      <p
        v-if="help"
        :id="helpId"
        class="mt-0.5 text-xs leading-relaxed text-gray-500 dark:text-gray-400"
      >
        {{ help }}
      </p>
    </div>
    <div
      :class="['min-w-0', wide ? '' : 'flex md:justify-end [&>*]:max-w-full']"
      role="group"
      :aria-labelledby="labelId"
      :aria-describedby="help ? helpId : undefined"
    >
      <slot />
    </div>
  </div>
</template>
