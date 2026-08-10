import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { usePolling } from './usePolling'
import { useConfigStore } from '../stores/config'
import { useGridStore } from '../stores/grid'
import { usePositionsStore } from '../stores/positions'
import { useSystemStore } from '../stores/system'

describe('usePolling', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('每 15 秒刷新一次参数配置', () => {
    const system = useSystemStore()
    const positions = usePositionsStore()
    const grid = useGridStore()
    const config = useConfigStore()

    vi.spyOn(system, 'fetchStatus').mockResolvedValue(undefined)
    vi.spyOn(system, 'fetchConnection').mockResolvedValue(undefined)
    vi.spyOn(positions, 'fetchOrders').mockResolvedValue(undefined)
    vi.spyOn(positions, 'fetchTrades').mockResolvedValue(undefined)
    vi.spyOn(positions, 'fetchPositions').mockResolvedValue(undefined)
    vi.spyOn(grid, 'fetchSessions').mockResolvedValue([] as any)
    vi.spyOn(config, 'fetchConfig').mockResolvedValue(undefined)

    let polling!: ReturnType<typeof usePolling>
    const wrapper = mount(defineComponent({
      setup() {
        polling = usePolling()
        return () => null
      },
    }))

    polling.start()

    vi.advanceTimersByTime(12_000)
    expect(config.fetchConfig).not.toHaveBeenCalled()

    vi.advanceTimersByTime(3_000)
    expect(config.fetchConfig).toHaveBeenCalledTimes(1)

    polling.stop()
    wrapper.unmount()
  })
})
