import { describe, it, expect } from 'vitest'
import { normalizeMetrics } from './metrics'

/**
 * 回归：汇总盈亏率曾被当作百分比直接展示，而两个后端返回的都是小数，
 * 导致 5.23% 显示成 0.05%；且 Flask 用 profit_ratio、网关用 total_profit_ratio，
 * 键名不一致时 Flask 直连模式恒显示 0.00%。
 */
describe('normalizeMetrics', () => {
  it('把网关的 total_profit_ratio 小数转成百分比数', () => {
    const m = normalizeMetrics({ total_profit_ratio: 0.0523 })
    expect(m.total_profit_ratio).toBeCloseTo(5.23, 6)
  })

  it('把 Flask 的 profit_ratio 小数转成百分比数', () => {
    const m = normalizeMetrics({ profit_ratio: 0.0523 })
    expect(m.total_profit_ratio).toBeCloseTo(5.23, 6)
  })

  it('total_profit_ratio 优先于 profit_ratio', () => {
    const m = normalizeMetrics({ total_profit_ratio: 0.01, profit_ratio: 0.99 })
    expect(m.total_profit_ratio).toBeCloseTo(1, 6)
  })

  it('负收益率保持负号', () => {
    const m = normalizeMetrics({ profit_ratio: -0.075 })
    expect(m.total_profit_ratio).toBeCloseTo(-7.5, 6)
  })

  it('null/undefined 输入返回全零而不抛错', () => {
    expect(normalizeMetrics(null).total_profit_ratio).toBe(0)
    expect(normalizeMetrics(undefined).total_market_value).toBe(0)
  })

  it('缺失字段按 0 处理，不产生 NaN', () => {
    const m = normalizeMetrics({})
    expect(m.total_profit_ratio).toBe(0)
    expect(m.total_profit).toBe(0)
    expect(Number.isNaN(m.total_market_value)).toBe(false)
  })

  it('非数值输入被吞掉而不是变成 NaN', () => {
    const m = normalizeMetrics({ total_profit: 'abc' as any, profit_ratio: null as any })
    expect(m.total_profit).toBe(0)
    expect(m.total_profit_ratio).toBe(0)
  })

  it('position_count 兼容 Flask 的 total_positions 键', () => {
    const m = normalizeMetrics({ total_positions: 7 })
    expect(m.position_count).toBe(7)
    expect(m.stock_count).toBe(7)
  })

  it('透传市值与盈亏金额（这两项后端已是绝对值，不做换算）', () => {
    const m = normalizeMetrics({ total_market_value: 123456.78, total_profit: -2345.6 })
    expect(m.total_market_value).toBeCloseTo(123456.78, 6)
    expect(m.total_profit).toBeCloseTo(-2345.6, 6)
  })
})
