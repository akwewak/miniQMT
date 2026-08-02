import { describe, it, expect } from 'vitest'
import { ageSeconds, freshnessOf, formatAge, freshnessClass, DEFAULT_THRESHOLD } from './freshness'

const T0 = 1_800_000_000_000 // 固定基准时刻，避免依赖真实时钟

describe('ageSeconds', () => {
  it('未更新过（0）返回 null 而不是 0 秒', () => {
    expect(ageSeconds(0, T0)).toBeNull()
  })

  it('计算经过的整秒数', () => {
    expect(ageSeconds(T0 - 12_000, T0)).toBe(12)
  })

  it('时钟回拨时不返回负数', () => {
    expect(ageSeconds(T0 + 5_000, T0)).toBe(0)
  })
})

describe('freshnessOf', () => {
  it('从未更新 → unknown', () => {
    expect(freshnessOf(0, DEFAULT_THRESHOLD, T0)).toBe('unknown')
  })

  it('阈值内 → fresh', () => {
    expect(freshnessOf(T0 - 5_000, DEFAULT_THRESHOLD, T0)).toBe('fresh')
  })

  it('恰好到 stale 阈值即判为 stale（边界含等号）', () => {
    expect(freshnessOf(T0 - 30_000, DEFAULT_THRESHOLD, T0)).toBe('stale')
  })

  it('stale 与 dead 之间 → stale', () => {
    expect(freshnessOf(T0 - 60_000, DEFAULT_THRESHOLD, T0)).toBe('stale')
  })

  it('恰好到 dead 阈值即判为 dead', () => {
    expect(freshnessOf(T0 - 90_000, DEFAULT_THRESHOLD, T0)).toBe('dead')
  })

  it('远超阈值 → dead', () => {
    expect(freshnessOf(T0 - 600_000, DEFAULT_THRESHOLD, T0)).toBe('dead')
  })

  it('支持自定义阈值', () => {
    expect(freshnessOf(T0 - 6_000, { stale: 5, dead: 10 }, T0)).toBe('stale')
    expect(freshnessOf(T0 - 11_000, { stale: 5, dead: 10 }, T0)).toBe('dead')
  })
})

describe('formatAge', () => {
  it('从未更新给出明确文案', () => {
    expect(formatAge(0, T0)).toBe('从未更新')
  })

  it('秒级', () => {
    expect(formatAge(T0 - 12_000, T0)).toBe('12 秒前')
  })

  it('分钟级（向下取整）', () => {
    expect(formatAge(T0 - 185_000, T0)).toBe('3 分钟前')
  })

  it('小时级', () => {
    expect(formatAge(T0 - 7_800_000, T0)).toBe('2 小时前')
  })

  it('59 秒仍按秒显示，60 秒进位到分钟', () => {
    expect(formatAge(T0 - 59_000, T0)).toBe('59 秒前')
    expect(formatAge(T0 - 60_000, T0)).toBe('1 分钟前')
  })
})

describe('freshnessClass', () => {
  it('dead 用红色以便一眼看出失联', () => {
    expect(freshnessClass('dead')).toContain('red')
  })

  it('stale 用琥珀色', () => {
    expect(freshnessClass('stale')).toContain('amber')
  })

  it('fresh / unknown 用中性色', () => {
    expect(freshnessClass('fresh')).toContain('slate')
    expect(freshnessClass('unknown')).toContain('slate')
  })
})
