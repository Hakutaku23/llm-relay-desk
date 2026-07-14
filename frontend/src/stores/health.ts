import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getHealth } from '@/api/health'
import { MalformedHealthResponseError, type HealthSummary } from '@/types/health'

export type HealthState = 'idle' | 'loading' | 'healthy' | 'malformed' | 'error'

export const useHealthStore = defineStore('health', () => {
  const state = ref<HealthState>('idle')
  const summary = ref<HealthSummary | null>(null)
  const errorMessage = ref('')

  async function load() {
    state.value = 'loading'
    summary.value = null
    errorMessage.value = ''
    try {
      summary.value = await getHealth()
      state.value = 'healthy'
    } catch (error) {
      if (error instanceof MalformedHealthResponseError) {
        state.value = 'malformed'
        errorMessage.value = error.message
      } else {
        state.value = 'error'
        errorMessage.value = error instanceof Error ? error.message : 'Health request failed.'
      }
    }
  }

  return { state, summary, errorMessage, load }
})
