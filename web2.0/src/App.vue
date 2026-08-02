<script setup lang="ts">
import { useSystemStore } from './stores/system'
import { useConfigStore } from './stores/config'
import { usePositionsStore } from './stores/positions'
import { useGridStore } from './stores/grid'
import { useSSE } from './composables/useSSE'
import { usePolling } from './composables/usePolling'
import { loadConnection } from './api/accounts'
import { computed, onMounted, onUnmounted, watch } from 'vue'

import HeaderBar from './components/HeaderBar.vue'
import SimulationBanner from './components/SimulationBanner.vue'
import ConfigPanel from './components/ConfigPanel.vue'
import TierSwitches from './components/TierSwitches.vue'
import HoldingsTable from './components/HoldingsTable.vue'
import GridStatusPanel from './components/GridStatusPanel.vue'
import PendingOrders from './components/PendingOrders.vue'
import OrderLog from './components/OrderLog.vue'
import AdviceTooltip from './components/AdviceTooltip.vue'

const system = useSystemStore()
const config = useConfigStore()
const positions = usePositionsStore()
const grid = useGridStore()
const { connect: sseConnect } = useSSE()
const { start: startPolling } = usePolling()

const mobilePnl = computed(() => positions.metrics.total_profit ?? 0)
const mobilePnlRatio = computed(() => positions.metrics.total_profit_ratio ?? 0)

async function init() {
  const conn = loadConnection()
  // xtquant 网关或 auto 模式：尝试从网关同步真实账号列表
  if (conn.mode === 'xtquant' || (conn.mode === 'auto' && conn.xtquantUrl && window.location.origin === conn.xtquantUrl)) {
    await system.syncAccountsFromGateway()
  }
  config.fetchConfig()
  await Promise.all([system.fetchStatus(), grid.fetchAll()])
  await positions.fetchAll()
  system.fetchConnection()
}

onMounted(() => {
  init(); setTimeout(() => sseConnect(), 1000); startPolling()
})
onUnmounted(() => {})

watch(() => system.currentAccountId, () => {
  positions.reset(); grid.reset()
  config.config = {}; config.updatedAt = 0
  init(); sseConnect()
})
</script>

<template>
  <div class="min-h-screen flex flex-col">
    <HeaderBar />
    <SimulationBanner />

    <main class="flex-1 p-3 md:p-5 space-y-3 md:space-y-5 max-w-[1600px] mx-auto w-full">
      <section class="md:hidden grid grid-cols-2 gap-2">
        <div class="metric-tile col-span-2">
          <div class="flex items-center justify-between gap-3">
            <div class="min-w-0">
              <div class="metric-label">总资产</div>
              <div class="metric-value truncate text-base">¥{{ (system.account.totalAssets || 0).toLocaleString() }}</div>
            </div>
            <div :class="['min-w-0 text-right font-mono text-sm font-semibold', mobilePnl >= 0 ? 'text-red-600' : 'text-emerald-600']">
              <div class="truncate">{{ mobilePnl >= 0 ? '+' : '' }}¥{{ Math.abs(mobilePnl).toLocaleString(undefined, { maximumFractionDigits: 2 }) }}</div>
              <div class="text-xs">{{ mobilePnlRatio >= 0 ? '+' : '' }}{{ mobilePnlRatio.toFixed(2) }}%</div>
            </div>
          </div>
        </div>
        <div class="metric-tile">
          <div class="metric-label">持仓</div>
          <div class="metric-value">{{ positions.positions.length }} 只</div>
        </div>
        <div class="metric-tile">
          <div class="metric-label">在途委托</div>
          <div :class="['metric-value', positions.pendingOrders.length ? 'text-amber-600' : '']">{{ positions.pendingOrders.length }} 笔</div>
        </div>
      </section>
      <ConfigPanel />
      <TierSwitches />
      <HoldingsTable />
      <PendingOrders />
      <GridStatusPanel />
      <OrderLog />
    </main>
  </div>
  <AdviceTooltip />
</template>
