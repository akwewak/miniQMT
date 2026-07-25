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

export function useAdviceTooltip() {
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

  async function show(event: MouseEvent, code: string) {
    if (!code) return

    const el = event.currentTarget as HTMLElement
    const rect = el.getBoundingClientRect()
    state.triggerRect = rect
    state.x = Math.max(8, rect.left)
    state.y = Math.max(8, rect.bottom + 8)
    state.ready = false

    const now = Date.now()
    const cached = cache[code]
    let data: any
    if (cached && now - cached.ts < TTL) {
      data = cached.data
    } else {
      data = await getMacdAdvice(code)
      cache[code] = { data, ts: now }
    }

    // 数据不足或网关模式降级：静默不显示
    if (!data || data.status !== 'success') {
      state.visible = false
      return
    }

    state.data = data
    state.visible = true
    await nextTick()
    placeTooltip()
    state.ready = true
  }

  function hide() {
    state.visible = false
    state.ready = false
  }

  return { state, show, hide }
}
