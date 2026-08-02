<script setup lang="ts">
import { computed } from 'vue'
import { useGridStore } from '../stores/grid'
import { fmtMoney, fmtPrice } from '../utils/format'

/**
 * 网格状态悬停卡（只读速览）。
 *
 * 数据直接取自已加载的会话列表，不额外发请求——悬停不应产生网络流量。
 * 比例字段后端已是小数，此处统一 ×100 显示，避免 web1.0 曾经的重复乘算问题。
 */
const props = defineProps<{
  stockCode: string
  anchor: { x: number; y: number }
}>()

const grid = useGridStore()
const session = computed(() => grid.getSessionByStock(props.stockCode))

const pnl = computed(() => session.value?.pnl_snapshot)

/** 网格盈亏率：优先真实账本口径 */
const profitRatio = computed(() => {
  const r = pnl.value?.profit_ratio ?? session.value?.profit_ratio
  return typeof r === 'number' ? r * 100 : null
})

const fundUsage = computed(() => {
  const cur = session.value?.current_investment
  const max = session.value?.max_investment
  if (!max) return null
  return { cur: cur || 0, max, pct: ((cur || 0) / max) * 100 }
})

const centerDeviation = computed(() => {
  const c0 = session.value?.center_price
  const c1 = session.value?.current_center_price
  if (!c0 || !c1) return null
  const ratio = ((c1 - c0) / c0) * 100
  return { ratio: Math.abs(ratio), dir: ratio >= 0 ? '上移' : '下移' }
})

const runtime = computed(() => {
  const start = session.value?.start_time
  if (!start) return '--'
  const ms = Date.now() - new Date(start).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '--'
  const d = Math.floor(ms / 86400000)
  const h = Math.floor((ms % 86400000) / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  if (d > 0) return `${d}天${h}小时`
  if (h > 0) return `${h}小时${m}分`
  return `${m}分钟`
})

const method = computed(() => {
  const map: Record<string, string> = {
    ledger_true_pnl: '真实账本',
    memory_true_pnl: '内存真实盈亏',
    cash_flow_legacy: '兼容降级',
  }
  const m = pnl.value?.method
  if (!m) return null
  return `${map[m] || m}${pnl.value?.is_degraded ? ' · 降级' : ''}`
})

const style = computed(() => ({
  left: `${Math.min(props.anchor.x, window.innerWidth - 280)}px`,
  top: `${props.anchor.y}px`,
}))

function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '--'
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed z-50 w-[264px] rounded-lg border border-slate-200 bg-white p-3 text-[11px] shadow-lg" :style="style">
      <div v-if="!session" class="text-slate-400">无网格会话数据</div>
      <template v-else>
        <div class="mb-2 flex items-center justify-between border-b border-slate-100 pb-1.5">
          <span class="font-mono font-semibold text-slate-700">{{ session.stock_code }}</span>
          <span class="text-slate-400">运行 {{ runtime }}</span>
        </div>
        <dl class="space-y-1">
          <div class="flex justify-between">
            <dt class="text-slate-400">网格盈亏</dt>
            <dd :class="['font-mono font-semibold', (profitRatio ?? 0) > 0 ? 'text-red-600' : (profitRatio ?? 0) < 0 ? 'text-emerald-600' : 'text-slate-500']">
              {{ pct(profitRatio) }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-slate-400">已实现 / 未实现</dt>
            <dd class="font-mono text-slate-600">
              {{ fmtMoney(pnl?.realized_pnl ?? 0, 0) }} / {{ fmtMoney(pnl?.unrealized_pnl ?? 0, 0) }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-slate-400">交易次数</dt>
            <dd class="font-mono text-slate-600">
              {{ session.trade_count ?? 0 }} (买{{ session.buy_count ?? 0 }}/卖{{ session.sell_count ?? 0 }})
            </dd>
          </div>
          <div v-if="fundUsage" class="flex justify-between">
            <dt class="text-slate-400">资金使用</dt>
            <dd class="font-mono text-slate-600">
              {{ fmtMoney(fundUsage.cur, 0) }} / {{ fmtMoney(fundUsage.max, 0) }} ({{ fundUsage.pct.toFixed(0) }}%)
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-slate-400">中心价</dt>
            <dd class="font-mono text-slate-600">
              {{ fmtPrice(session.center_price) }} → {{ fmtPrice(session.current_center_price) }}
            </dd>
          </div>
          <div v-if="centerDeviation" class="flex justify-between">
            <dt class="text-slate-400">中心价偏离</dt>
            <dd class="font-mono text-slate-600">{{ centerDeviation.ratio.toFixed(2) }}% {{ centerDeviation.dir }}</dd>
          </div>
          <div v-if="method" class="flex justify-between border-t border-slate-100 pt-1">
            <dt class="text-slate-400">口径</dt>
            <dd class="text-slate-500">{{ method }}</dd>
          </div>
        </dl>
      </template>
    </div>
  </Teleport>
</template>
