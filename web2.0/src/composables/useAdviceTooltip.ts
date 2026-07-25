import { reactive } from 'vue'
import { getMacdAdvice } from '../api/flask'

// 模块级单例状态：全局共享一个悬浮窗
const state = reactive({
  visible: false,
  x: 0,
  y: 0,
  data: null as any,
})

const cache: Record<string, { data: any; ts: number }> = {}
const TTL = 300000 // 5 分钟

export function useAdviceTooltip() {
  async function show(event: MouseEvent, code: string) {
    if (!code) return
    const el = event.currentTarget as HTMLElement
    const rect = el.getBoundingClientRect()
    let left = rect.left
    let top = rect.bottom + 8
    // 下方空间不够(迷你图约250px高) → 翻到上方
    const estH = 260
    if (rect.bottom + estH > window.innerHeight) {
      top = rect.top - estH - 8
    }
    state.x = Math.max(8, Math.min(left, window.innerWidth - 480))
    state.y = Math.max(8, top)

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
  }

  function hide() {
    state.visible = false
  }

  return { state, show, hide }
}
