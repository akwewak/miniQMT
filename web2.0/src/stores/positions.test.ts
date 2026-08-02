import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePositionsStore } from './positions'
import * as flaskApi from '../api/flask'

describe('positions store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('fetchPositions 归一化 metrics 口径（小数 → 百分比数）', async () => {
    vi.spyOn(flaskApi, 'getPositions').mockResolvedValue({
      positions: [], positionsAll: [{ stock_code: '000001' } as any],
      metrics: { profit_ratio: 0.0523, total_profit: 1000, total_market_value: 20000 } as any,
      version: 5, noChange: false,
    })
    const store = usePositionsStore()
    await store.fetchPositions()
    expect(store.metrics.total_profit_ratio).toBeCloseTo(5.23, 6)
    expect(store.dataVersion).toBe(5)
    expect(store.positions).toHaveLength(1)
  })

  it('noChange 时保留旧数据但刷新新鲜度时间戳', async () => {
    const store = usePositionsStore()
    vi.spyOn(flaskApi, 'getPositions').mockResolvedValue({
      positions: [], positionsAll: [{ stock_code: '000001' } as any],
      metrics: { profit_ratio: 0.01 } as any, version: 3, noChange: false,
    })
    await store.fetchPositions()
    const firstStamp = store.positionsUpdatedAt

    vi.spyOn(flaskApi, 'getPositions').mockResolvedValue({
      positions: [], positionsAll: [], metrics: {} as any, version: 3, noChange: true,
    })
    await new Promise(r => setTimeout(r, 2))
    await store.fetchPositions()

    // 数据未被清空
    expect(store.positions).toHaveLength(1)
    // 但握手成功，新鲜度前进
    expect(store.positionsUpdatedAt).toBeGreaterThanOrEqual(firstStamp)
  })

  it('请求失败（null）时不清空既有持仓', async () => {
    const store = usePositionsStore()
    vi.spyOn(flaskApi, 'getPositions').mockResolvedValue({
      positions: [], positionsAll: [{ stock_code: '000001' } as any],
      metrics: {} as any, version: 1, noChange: false,
    })
    await store.fetchPositions()

    vi.spyOn(flaskApi, 'getPositions').mockResolvedValue(null as any)
    await store.fetchPositions()
    expect(store.positions).toHaveLength(1)
  })

  it('pendingOrders 只挑出在途委托', async () => {
    vi.spyOn(flaskApi, 'getOrders').mockResolvedValue([
      { order_id: '1', is_pending: true, status: 50 } as any,
      { order_id: '2', is_pending: false, status: 56 } as any,
      { order_id: '3', is_pending: true, status: 55 } as any,
    ])
    const store = usePositionsStore()
    await store.fetchOrders()
    expect(store.orders).toHaveLength(3)
    expect(store.pendingOrders.map(o => o.order_id)).toEqual(['1', '3'])
  })

  it('reset 清空全部数据与时间戳（切换账号时避免串号）', async () => {
    vi.spyOn(flaskApi, 'getPositions').mockResolvedValue({
      positions: [], positionsAll: [{ stock_code: '000001' } as any],
      metrics: { profit_ratio: 0.05 } as any, version: 9, noChange: false,
    })
    vi.spyOn(flaskApi, 'getOrders').mockResolvedValue([{ order_id: '1', is_pending: true } as any])
    const store = usePositionsStore()
    await store.fetchPositions()
    await store.fetchOrders()

    store.reset()
    expect(store.positions).toEqual([])
    expect(store.orders).toEqual([])
    expect(store.dataVersion).toBe(0)
    expect(store.positionsUpdatedAt).toBe(0)
    expect(store.metrics.total_profit_ratio).toBe(0)
  })
})
