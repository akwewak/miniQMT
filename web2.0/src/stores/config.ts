import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ConfigData } from '../types'
import * as flaskApi from '../api/flask'

/**
 * 交易参数的只读快照。
 *
 * 不再预置一组"默认值"——那会让读不到配置时也显示出一组看似真实的数字。
 * 缺失的键保持 undefined，由 UI 渲染成 "--"。
 */
export const useConfigStore = defineStore('config', () => {
  const config = ref<Partial<ConfigData>>({})
  const loading = ref(false)
  const updatedAt = ref(0)

  async function fetchConfig() {
    loading.value = true
    const r = await flaskApi.getConfig()
    if (r) {
      config.value = r.data || {}
      updatedAt.value = Date.now()
    }
    loading.value = false
  }

  return { config, loading, updatedAt, fetchConfig }
})
