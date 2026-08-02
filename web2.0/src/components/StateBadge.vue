<script setup lang="ts">
import { computed } from 'vue'
import type { TriState } from '../types'

/**
 * 三态只读状态徽章。
 *
 * null 必须显示为"未知"而非"关闭"——网关模式下部分开关无法获知真实值，
 * 把未知渲染成关闭会让监控者误判系统正处于安全状态。
 */
const props = defineProps<{
  label: string
  value: TriState
  /** 值为 true 时是否用警示色（如"模拟交易"开启时） */
  warnOnTrue?: boolean
}>()

const text = computed(() => props.value === null ? '未知' : (props.value ? '开' : '关'))

const cls = computed(() => {
  if (props.value === null) return 'bg-slate-50 text-slate-400 ring-slate-200'
  if (props.value) {
    return props.warnOnTrue
      ? 'bg-amber-50 text-amber-700 ring-amber-200'
      : 'bg-emerald-50 text-emerald-700 ring-emerald-200'
  }
  return 'bg-slate-100 text-slate-500 ring-slate-200'
})

const tip = computed(() =>
  props.value === null
    ? `${props.label}：状态未知 —— 该开关只存在于主进程内存，网关需反向探测其 Flask 才能读到；`
      + `若主程序以 web2.0 模式启动（无 Flask），此项将持续未知`
    : `${props.label}：${props.value ? '已开启' : '已关闭'}`
)
</script>

<template>
  <span
    :class="['inline-flex flex-shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] ring-1', cls]"
    :title="tip"
  >
    <span class="text-slate-500">{{ label }}</span>
    <strong class="font-semibold">{{ text }}</strong>
  </span>
</template>
