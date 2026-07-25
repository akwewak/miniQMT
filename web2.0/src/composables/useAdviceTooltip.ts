import { nextTick, reactive } from 'vue'
import { getMacdAdvice } from '../api/flask'

// 模块级单例状态：全局共享一个悬浮窗
const state = reactive({
  visible: false,
  ready: false,
  x: 0,
  y: 0,
  data: null as any,
  triggerRect: null as DOMRect | null,
})

const cache: Record<string, { data: any; ts: number }> = {}
const TTL = 300000 // 5 分钟
let requestSeq = 0

export function useAdviceTooltip() {
  function makeStatusAdvice(code: string, trend: string, message: string) {
    return {
      status: 'success',
      code,
      trend,
      base_position: '--',
      grid: '--',
      cross: message,
      dif: null,
      dea: null,
      updated: '',
      series: [],
      is_status: true,
    }
  }

  function placeTooltip() {
    const rect = state.triggerRect
    const tooltip = document.querySelector('.advice-tooltip') as HTMLElement | null
    if (!rect || !tooltip) return

    const margin = 8
    const tooltipRect = tooltip.getBoundingClientRect()
    const tooltipWidth = Math.min(tooltipRect.width, window.innerWidth - margin * 2)
    const tooltipHeight = Math.min(tooltipRect.height, window.innerHeight - margin * 2)

    let left = rect.left
    if (left + tooltipWidth + margin > window.innerWidth) {
      left = window.innerWidth - tooltipWidth - margin
    }
    left = Math.max(margin, left)

    let top = rect.bottom + margin
    if (top + tooltipHeight + margin > window.innerHeight) {
      top = rect.top - tooltipHeight - margin
    }
    if (top < margin) {
      top = Math.max(margin, Math.min(rect.bottom + margin, window.innerHeight - tooltipHeight - margin))
    }

    state.x = left
    state.y = top
  }

  async function show(event: Event, code: string) {
    if (!code) return

    const el = event.currentTarget as HTMLElement
    const rect = el.getBoundingClientRect()
    const currentSeq = ++requestSeq
    state.triggerRect = rect
    state.x = Math.max(8, rect.left)
    state.y = Math.max(8, rect.bottom + 8)
    state.ready = false
    state.data = makeStatusAdvice(code, '加载操作建议...', '正在获取 MACD 数据')
    state.visible = true
    await nextTick()
    placeTooltip()
    state.ready = true

    const now = Date.now()
    const cached = cache[code]
    let data: any
    try {
      if (cached && now - cached.ts < TTL) {
        data = cached.data
      } else {
        data = await getMacdAdvice(code)
        cache[code] = { data, ts: now }
      }
    } catch (e: any) {
      data = { status: 'error', message: e?.message || '请求失败' }
    }

    if (currentSeq !== requestSeq) return

    // 数据不足或接口不可用时，也给用户明确反馈
    if (!data || data.status !== 'success') {
      state.data = makeStatusAdvice(code, '操作建议不可用', data?.message || data?.error || '接口未返回可用建议')
    } else {
      state.data = data
    }
    await nextTick()
    placeTooltip()
    state.ready = true
  }

  function hide() {
    requestSeq += 1
    state.visible = false
    state.ready = false
  }

  return { state, show, hide }
}
