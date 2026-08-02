<script setup lang="ts">
import { computed } from 'vue'
import { useConfigStore } from '../stores/config'
import { formatAge } from '../utils/freshness'

/**
 * 交易参数只读面板。
 *
 * web2.0 不提供参数编辑——修改请使用 web1.0（Flask 直连，仅绑本机）。
 * 读不到的值渲染为 "--"，绝不用默认值冒充真实配置。
 */
const store = useConfigStore()

type Field = { label: string; key: string; suffix?: string; decimals?: number; bool?: boolean }

const FIELDS: Field[] = [
  { label: '单次买入金额', key: 'singleBuyAmount', suffix: '元', decimals: 0 },
  { label: '单股最大持仓', key: 'singleStockMaxPosition', suffix: '元', decimals: 0 },
  { label: '最大总持仓', key: 'totalMaxPosition', suffix: '元', decimals: 0 },
  { label: '止损比例', key: 'stockStopLoss', suffix: '%', decimals: 2 },
  { label: '补仓跌幅阈值', key: 'stopLossBuy', suffix: '%', decimals: 2 },
  { label: '首次止盈阈值', key: 'firstProfitSell', suffix: '%', decimals: 2 },
  { label: '首次卖出比例', key: 'stockGainSellPencent', suffix: '%', decimals: 2 },
  { label: '首次止盈启用', key: 'firstProfitSellEnabled', bool: true },
  { label: '补仓功能启用', key: 'stopLossBuyEnabled', bool: true },
]

function display(f: Field): string {
  const raw = (store.config as any)[f.key]
  if (raw === null || raw === undefined) return '--'
  if (f.bool) return raw ? '开' : '关'
  const n = Number(raw)
  if (!Number.isFinite(n)) return '--'
  return n.toFixed(f.decimals ?? 0)
}

const age = computed(() => formatAge(store.updatedAt))
const hasData = computed(() => Object.keys(store.config).length > 0)
</script>

<template>
  <div class="card">
    <div class="card-header flex items-center justify-between">
      <div>
        <span>参数设置</span>
        <div class="text-[10px] font-normal text-slate-400">只读 · 修改请使用 web1.0</div>
      </div>
      <span class="text-[10px] text-slate-400 font-mono">{{ age }}</span>
    </div>
    <div class="card-body !py-3">
      <p v-if="!hasData" class="text-xs text-slate-400 py-2">暂无参数数据（后端未返回配置）</p>
      <div v-else class="grid grid-cols-2 lg:grid-cols-3 gap-2 md:gap-x-6 md:gap-y-2">
        <div v-for="f in FIELDS" :key="f.key"
          class="rounded-lg border border-slate-200/70 bg-slate-50/60 p-2 md:flex md:items-center md:gap-1.5 md:border-0 md:bg-transparent md:p-0">
          <span class="block text-[11px] text-slate-500 md:w-[84px] md:text-right md:flex-shrink-0">{{ f.label }}</span>
          <div class="mt-1 flex items-baseline gap-1 md:mt-0">
            <strong class="font-mono text-xs text-slate-700 tabular-nums">{{ display(f) }}</strong>
            <span v-if="f.suffix" class="text-[11px] text-slate-400">{{ f.suffix }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
