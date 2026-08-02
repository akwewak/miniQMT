<script setup lang="ts">
import { useSystemStore } from './stores/system'
import { useConfigStore } from './stores/config'
import { usePositionsStore } from './stores/positions'
import { useGridStore } from './stores/grid'
import { useSSE } from './composables/useSSE'
import { usePolling } from './composables/usePolling'
import { loadConnection } from './api/accounts'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

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

type Page = 'dashboard' | 'grid' | 'orders' | 'trades'

const mobilePnl = computed(() => positions.metrics.total_profit ?? 0)
const mobilePnlRatio = computed(() => positions.metrics.total_profit_ratio ?? 0)
const page = ref<Page>(pageFromHash())
const secondaryTitle = computed(() => {
  const titles: Record<Exclude<Page, 'dashboard'>, string> = {
    grid: '网格交易状态',
    orders: '委托队列',
    trades: '成交记录',
  }
  return page.value === 'dashboard' ? '' : titles[page.value]
})
const orderCount = computed(() => positions.orders.length)
const tradeCount = computed(() => positions.trades.length)

function pageFromHash(): Page {
  const route = window.location.hash.replace(/^#\/?/, '').split('?')[0]
  if (route === 'grid') return 'grid'
  if (route === 'orders') return 'orders'
  if (route === 'trades') return 'trades'
  return 'dashboard'
}

function syncPage() {
  page.value = pageFromHash()
}

function goPage(next: Page) {
  window.location.hash = next === 'dashboard' ? '' : next
  syncPage()
}

function activePageClass(target: Page) {
  return page.value === target ? 'btn-primary btn-xs' : 'btn-outline btn-xs'
}

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
  window.addEventListener('hashchange', syncPage)
})
onUnmounted(() => {
  window.removeEventListener('hashchange', syncPage)
})

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
      <template v-if="page === 'dashboard'">
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
        <section class="grid grid-cols-1 md:grid-cols-3 gap-3">
          <button @click="goPage('grid')" class="metric-tile flex items-center justify-between gap-3 text-left transition-colors hover:border-blue-200 hover:bg-blue-50/40">
            <div class="min-w-0">
              <div class="metric-label">网格交易状态</div>
              <div class="metric-value">{{ grid.sessions.length }} 个会话</div>
              <div v-if="grid.activeSessions.length" class="mt-1 text-[11px] font-medium text-emerald-600">{{ grid.activeSessions.length }} 个运行中</div>
            </div>
            <svg class="h-4 w-4 flex-shrink-0 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
            </svg>
          </button>
          <button @click="goPage('orders')" class="metric-tile flex items-center justify-between gap-3 text-left transition-colors hover:border-blue-200 hover:bg-blue-50/40">
            <div class="min-w-0">
              <div class="metric-label">委托队列</div>
              <div :class="['metric-value', positions.pendingOrders.length ? 'text-amber-600' : '']">{{ positions.pendingOrders.length }} 笔在途</div>
              <div v-if="orderCount" class="mt-1 text-[11px] font-medium text-slate-400">当日 {{ orderCount }} 笔</div>
            </div>
            <svg class="h-4 w-4 flex-shrink-0 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
            </svg>
          </button>
          <button @click="goPage('trades')" class="metric-tile flex items-center justify-between gap-3 text-left transition-colors hover:border-blue-200 hover:bg-blue-50/40">
            <div class="min-w-0">
              <div class="metric-label">成交记录</div>
              <div class="metric-value">{{ tradeCount }} 条</div>
            </div>
            <svg class="h-4 w-4 flex-shrink-0 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
            </svg>
          </button>
        </section>
      </template>

      <template v-else>
        <section class="flex flex-wrap items-center justify-between gap-2">
          <button @click="goPage('dashboard')" class="btn-outline btn-xs">
            <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
            </svg>
            <span>主页面</span>
          </button>
          <h2 class="min-w-0 flex-1 truncate text-sm font-semibold text-slate-700 md:text-base">{{ secondaryTitle }}</h2>
          <div class="flex items-center gap-2">
            <button @click="goPage('grid')" :class="activePageClass('grid')">网格</button>
            <button @click="goPage('orders')" :class="activePageClass('orders')">委托</button>
            <button @click="goPage('trades')" :class="activePageClass('trades')">成交</button>
          </div>
        </section>
        <GridStatusPanel v-if="page === 'grid'" />
        <PendingOrders v-else-if="page === 'orders'" />
        <OrderLog v-else />
      </template>
    </main>
  </div>
  <AdviceTooltip />
</template>
