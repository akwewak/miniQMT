import { ref, onUnmounted } from 'vue'
import { useSystemStore } from '../stores/system'
import { usePositionsStore } from '../stores/positions'
import { useGridStore } from '../stores/grid'
import { useConfigStore } from '../stores/config'

/**
 * 分级轮询。
 *
 * 监控端唯一的数据来源保障——轮询不因任何业务开关而停止，
 * 只随页面可见性调整频率。QMT 连接状态也必须在此持续刷新，
 * 否则掉线后顶栏指示灯会永远停在"已连接"。
 */
export function usePolling() {
  const system = useSystemStore()
  const positions = usePositionsStore()
  const grid = useGridStore()
  const config = useConfigStore()

  const BASE_INTERVAL = 3000
  const HIDDEN_INTERVAL = 15000

  const interval = ref(BASE_INTERVAL)
  let timer: ReturnType<typeof setInterval> | null = null
  let tick = 0

  // 各任务的触发周期（单位：tick）。3s 基准下 → 9s / 15s / 15s / 15s / 18s / 30s
  const EVERY = {
    status: 3,
    connection: 5,
    config: 5,
    orders: 5,
    trades: 6,
    positions: 10,
  }

  function start(customInterval = BASE_INTERVAL) {
    stop()
    interval.value = customInterval
    tick = 0
    timer = setInterval(poll, interval.value)
  }

  function stop() {
    if (timer) { clearInterval(timer); timer = null }
  }

  function restart(next: number) {
    if (next === interval.value && timer) return
    start(next)
  }

  async function poll() {
    tick++
    if (tick % EVERY.status === 0) system.fetchStatus().catch(() => {})
    // 连接状态必须轮询：这是 QMT 掉线时唯一的可见信号
    if (tick % EVERY.connection === 0) system.fetchConnection().catch(() => {})
    if (tick % EVERY.config === 0) config.fetchConfig().catch(() => {})
    if (tick % EVERY.orders === 0) positions.fetchOrders().catch(() => {})
    if (tick % EVERY.trades === 0) positions.fetchTrades().catch(() => {})
    if (tick % EVERY.positions === 0) {
      grid.fetchSessions().then(() => positions.fetchPositions()).catch(() => {})
    }
    if (tick >= 30) tick = 0
  }

  // 页面不可见时降频，回到前台立即补一次全量刷新
  function onVisibilityChange() {
    if (document.hidden) {
      restart(HIDDEN_INTERVAL)
    } else {
      restart(BASE_INTERVAL)
      system.fetchStatus().catch(() => {})
      system.fetchConnection().catch(() => {})
      config.fetchConfig().catch(() => {})
      positions.fetchAll().catch(() => {})
      grid.fetchSessions().catch(() => {})
    }
  }

  document.addEventListener('visibilitychange', onVisibilityChange)

  onUnmounted(() => {
    document.removeEventListener('visibilitychange', onVisibilityChange)
    stop()
  })

  return { start, stop, interval }
}
