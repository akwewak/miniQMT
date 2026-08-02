<script setup lang="ts">
import { computed } from 'vue'
import { useSystemStore } from '../stores/system'
import { usePositionsStore } from '../stores/positions'
import { useGridStore } from '../stores/grid'
import { summarizeStopProfit, summarizeGridSessions, chainEffective } from '../utils/tiers'
import type { TriState } from '../types'

/**
 * 三级开关状态总览（只读）。
 *
 * 自动止盈止损和网格交易各有一条三级门控链，任何一级关闭则策略不产生新单。
 * 对监控者而言，一眼看清整条链路比逐项排查重要。
 */

const system = useSystemStore()
const positions = usePositionsStore()
const grid = useGridStore()

interface Tier {
  label: string
  key: string
  value: TriState
}

const stopProfitTiers = computed<Tier[]>(() => [
  { label: '全局总闸', key: 'auto_op', value: system.isMonitoring },
  { label: '自动止盈', key: 'auto_trade', value: system.autoTrading },
])

const gridTiers = computed<Tier[]>(() => [
  { label: '全局总闸', key: 'auto_op', value: system.isMonitoring },
  { label: '自动网格', key: 'grid', value: system.gridTrading },
])

const stopProfitStocks = computed(() => summarizeStopProfit(positions.positions))
const gridSessions = computed(() => summarizeGridSessions(grid.sessions))

// 前两级的合成结果，决定整体标题的色调
const stopProfitChain = computed(() =>
  chainEffective(system.isMonitoring, system.autoTrading))
const gridChain = computed(() =>
  chainEffective(system.isMonitoring, system.gridTrading))

function triLabel(v: TriState): string {
  return v === null ? '?' : (v ? '✔' : '✘')
}

function triColor(v: TriState): string {
  if (v === null) return 'bg-slate-100 text-slate-400'
  return v ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-600'
}

function chainHint(v: TriState, name: string): string {
  if (v === false) return `${name}已被前两级开关阻断，不会产生新单`
  if (v === null) return `${name}的部分开关状态未知，无法确认是否在运行`
  return `${name}前两级开关均已开启`
}

function tierTip(t: Tier): string {
  if (t.value !== null) return `${t.label}：${t.value ? '已开启' : '已关闭'}`
  // 未知的成因对排查很关键，不能只写"后端未提供"
  if (t.key === 'auto_op') {
    return '全局总闸：状态未知 —— ENABLE_AUTO_OPERATION 只存在于主进程内存'
      + '（按设计不持久化，每次启动需手动确认）。网关通过反向探测该账号的'
      + ' Flask 读取；若主程序以 web2.0 模式启动（QMT_NO_FLASK=1，无 Flask），'
      + '此项将持续未知'
  }
  return `${t.label}：状态未知，后端未返回该开关`
}
</script>

<template>
  <div class="card !py-2">
    <div class="flex flex-wrap items-stretch gap-2 md:gap-4">
      <!-- 自动止盈止损 -->
      <div class="flex-1 min-w-[200px] rounded-lg border border-slate-200/80 bg-white p-2">
        <div class="mb-1.5 flex items-center justify-between">
          <span class="text-[11px] font-semibold text-slate-600" :title="chainHint(stopProfitChain, '动态止盈止损')">
            动态止盈止损
            <span :class="stopProfitChain === false ? 'text-red-500' : stopProfitChain === null ? 'text-slate-400' : 'text-emerald-600'">
              {{ triLabel(stopProfitChain) }}
            </span>
          </span>
          <span class="badge-slate !text-[9px] !px-1"
            :title="`个股级开关：${stopProfitStocks.enabled} 只开启 / ${stopProfitStocks.disabled} 只暂停` +
                    (stopProfitStocks.unknown ? ` / ${stopProfitStocks.unknown} 只未知` : '') +
                    '（明细见持仓列表末列）'">
            个股 {{ stopProfitStocks.enabled }}/{{ stopProfitStocks.total }}
          </span>
        </div>
        <div class="flex flex-wrap items-center gap-1.5">
          <span
            v-for="t in stopProfitTiers" :key="t.key"
            :class="['inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium', triColor(t.value)]"
            :title="tierTip(t)"
          >
            <span>{{ triLabel(t.value) }}</span><span>{{ t.label }}</span>
          </span>
          <span class="text-[10px] text-slate-300">›</span>
          <span class="rounded bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500"
            title="第 3 级：个股级 stop_profit_enabled">个股级</span>
        </div>
      </div>

      <!-- 网格交易 -->
      <div class="flex-1 min-w-[200px] rounded-lg border border-slate-200/80 bg-white p-2">
        <div class="mb-1.5 flex items-center justify-between">
          <span class="text-[11px] font-semibold text-slate-600" :title="chainHint(gridChain, '网格交易')">
            网格交易
            <span :class="gridChain === false ? 'text-red-500' : gridChain === null ? 'text-slate-400' : 'text-emerald-600'">
              {{ triLabel(gridChain) }}
            </span>
          </span>
          <span v-if="gridSessions.total" class="badge-slate !text-[9px] !px-1"
            :title="`会话级开关：${gridSessions.enabled} 个自动 / ${gridSessions.paused} 个暂停`">
            会话 {{ gridSessions.enabled }}/{{ gridSessions.total }}
          </span>
          <span v-else class="badge-slate !text-[9px] !px-1" title="当前没有网格会话">无会话</span>
        </div>
        <div class="flex flex-wrap items-center gap-1.5">
          <span
            v-for="t in gridTiers" :key="t.key"
            :class="['inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium', triColor(t.value)]"
            :title="tierTip(t)"
          >
            <span>{{ triLabel(t.value) }}</span><span>{{ t.label }}</span>
          </span>
          <span class="text-[10px] text-slate-300">›</span>
          <span class="rounded bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500"
            title="第 3 级：会话级 grid_trading_sessions.enabled">会话级</span>
        </div>
      </div>
    </div>
  </div>
</template>
