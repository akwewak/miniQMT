<script setup lang="ts">
import { computed, ref } from 'vue'
import { usePositionsStore } from '../stores/positions'
import { formatAge } from '../utils/freshness'

/**
 * 委托列表（在途优先）。
 *
 * 这是监控端此前的盲区：止盈卖单提交后、成交回报到达前，
 * 持仓和成交记录都看不到它，只有委托队列能证明"单已挂出"。
 */
const positions = usePositionsStore()
const showAll = ref(true)

const pending = computed(() => positions.pendingOrders)
const visible = computed(() => showAll.value ? positions.orders : pending.value)
const age = computed(() => formatAge(positions.ordersUpdatedAt))

/** 部分成交进度 */
function progress(o: any): string {
  const done = o.traded_volume || 0
  const total = o.volume || 0
  if (!total) return '--'
  return `${done}/${total}`
}

function timeOf(o: any): string {
  return (o.order_time || '').substring(11, 19) || '--'
}
</script>

<template>
  <div class="card">
    <div class="card-header">
      <div class="flex items-center gap-2">
        <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>
        <span>委托队列</span>
        <span v-if="pending.length" class="badge-amber text-[10px]">{{ pending.length }} 笔在途</span>
        <span v-else class="badge-slate text-[10px]">无在途</span>
      </div>
      <div class="flex items-center gap-2">
        <button class="text-[10px] text-blue-600 hover:underline" @click="showAll = !showAll">
          {{ showAll ? '仅看在途' : `看全部 (${positions.orders.length})` }}
        </button>
        <span class="text-[10px] text-slate-400 font-mono">{{ age }}</span>
      </div>
    </div>

    <div class="p-0">
      <div v-if="visible.length === 0" class="py-10 text-center">
        <p class="text-slate-400 text-sm">{{ showAll ? '当日无委托记录' : '当前没有未成交委托' }}</p>
        <p class="text-slate-300 text-[11px] mt-1">止盈/网格挂单提交后会在此实时出现</p>
      </div>

      <div v-else class="max-h-[280px] overflow-y-auto overflow-x-auto">
        <div class="min-w-[620px] md:min-w-0 divide-y divide-slate-50">
          <div v-for="o in visible" :key="o.order_id"
            :class="['flex items-center gap-2 md:gap-3 px-3 md:px-4 py-2.5 text-xs transition-colors',
                     o.is_pending ? 'bg-amber-50/40 hover:bg-amber-50/70' : 'hover:bg-slate-50/60']">
            <span class="text-[11px] text-slate-400 font-mono w-16 flex-shrink-0">{{ timeOf(o) }}</span>
            <span :class="['inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold w-10 justify-center flex-shrink-0',
              o.trade_type === 'BUY' ? 'bg-red-50 text-red-600 ring-1 ring-red-200' : 'bg-emerald-50 text-emerald-600 ring-1 ring-emerald-200']">
              {{ o.trade_type === 'BUY' ? '买入' : '卖出' }}
            </span>
            <span class="font-mono font-medium text-slate-700 w-16 flex-shrink-0">{{ o.stock_code }}</span>
            <span class="text-slate-500 truncate w-16 flex-shrink-0">{{ o.stock_name || '--' }}</span>
            <span class="font-mono text-slate-600 w-14 text-right flex-shrink-0">{{ (o.price || 0).toFixed(2) }}</span>
            <span class="text-slate-400 w-20 text-right flex-shrink-0 font-mono" title="已成交/委托总量">{{ progress(o) }}</span>
            <span :class="['badge !text-[9px] flex-shrink-0', o.is_pending ? 'badge-amber' : 'badge-slate']">
              {{ o.status_desc }}
            </span>
            <span v-if="o.strategy" class="badge-slate !text-[9px] flex-shrink-0 hidden md:inline">{{ o.strategy }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
