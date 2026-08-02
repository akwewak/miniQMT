import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Position, PositionMetrics, TradeRecord, OrderRecord } from '../types'
import { normalizeMetrics } from '../utils/metrics'
import * as flaskApi from '../api/flask'

export const usePositionsStore = defineStore('positions', () => {
  const positions = ref<Position[]>([])
  const metrics = ref<PositionMetrics>(normalizeMetrics(null))
  const trades = ref<TradeRecord[]>([])
  const orders = ref<OrderRecord[]>([])
  const dataVersion = ref(0)
  const loading = ref(false)

  // 各数据块的最后成功刷新时刻（epoch ms），供新鲜度指示使用
  const positionsUpdatedAt = ref(0)
  const tradesUpdatedAt = ref(0)
  const ordersUpdatedAt = ref(0)

  const hasPositions = computed(() => positions.value.length > 0)
  const totalMarketValue = computed(() => metrics.value.total_market_value)

  /** 在途委托：已报未成交，是监控视图的关键盲区补齐项 */
  const pendingOrders = computed(() => orders.value.filter(o => o.is_pending))

  async function fetchPositions() {
    const r = await flaskApi.getPositions(dataVersion.value)
    if (!r) return
    // noChange 也代表一次成功握手，刷新新鲜度但不动数据
    positionsUpdatedAt.value = Date.now()
    if (r.noChange) return
    positions.value = r.positionsAll
    metrics.value = normalizeMetrics(r.metrics)
    dataVersion.value = r.version
  }

  async function fetchTrades() {
    trades.value = await flaskApi.getTradeRecords()
    tradesUpdatedAt.value = Date.now()
  }

  async function fetchOrders() {
    orders.value = await flaskApi.getOrders()
    ordersUpdatedAt.value = Date.now()
  }

  async function fetchAll() {
    loading.value = true
    await Promise.all([fetchPositions(), fetchTrades(), fetchOrders()])
    loading.value = false
  }

  function reset() {
    positions.value = []
    trades.value = []
    orders.value = []
    metrics.value = normalizeMetrics(null)
    dataVersion.value = 0
    positionsUpdatedAt.value = 0
    tradesUpdatedAt.value = 0
    ordersUpdatedAt.value = 0
  }

  return {
    positions, metrics, trades, orders, dataVersion, loading,
    positionsUpdatedAt, tradesUpdatedAt, ordersUpdatedAt,
    hasPositions, totalMarketValue, pendingOrders,
    fetchPositions, fetchTrades, fetchOrders, fetchAll, reset,
  }
})
