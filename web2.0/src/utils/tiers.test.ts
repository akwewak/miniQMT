import { describe, it, expect } from 'vitest'
import { summarizeStopProfit, summarizeGridSessions, chainEffective } from './tiers'
import type { Position, GridSession } from '../types'

function pos(over: Partial<Position> = {}): Position {
  return {
    stock_code: '000001', volume: 100, available: 100,
    cost_price: 10, current_price: 10, market_value: 1000,
    profit_ratio: 0, profit_triggered: false, highest_price: 10,
    stop_loss_price: 9, open_date: '2026-08-01', grid_session_active: false,
    ...over,
  }
}

function session(over: Partial<GridSession> = {}): GridSession {
  return {
    session_id: 1, stock_code: '000001', status: 'active',
    center_price: 10, current_center_price: 10,
    trade_count: 0, buy_count: 0, sell_count: 0,
    profit_ratio: 0, deviation_ratio: 0,
    start_time: '2026-08-01', end_time: '2026-08-08',
    ...over,
  }
}

describe('summarizeStopProfit（个股级止盈开关聚合）', () => {
  it('空持仓返回全零', () => {
    expect(summarizeStopProfit([])).toEqual({ total: 0, enabled: 0, disabled: 0, unknown: 0 })
  })

  it('区分开启与关闭', () => {
    const s = summarizeStopProfit([
      pos({ stop_profit_enabled: true }),
      pos({ stop_profit_enabled: true }),
      pos({ stop_profit_enabled: false }),
    ])
    expect(s).toEqual({ total: 3, enabled: 2, disabled: 1, unknown: 0 })
  })

  it('字段缺失计入 unknown，不冒充成已开启', () => {
    const s = summarizeStopProfit([pos({}), pos({ stop_profit_enabled: true })])
    expect(s.unknown).toBe(1)
    expect(s.enabled).toBe(1)
  })

  it('全部关闭时 enabled 为 0（该策略实际上被逐股停掉了）', () => {
    const s = summarizeStopProfit([
      pos({ stop_profit_enabled: false }),
      pos({ stop_profit_enabled: false }),
    ])
    expect(s.enabled).toBe(0)
    expect(s.disabled).toBe(2)
  })

  it('三类之和恒等于 total', () => {
    const s = summarizeStopProfit([
      pos({ stop_profit_enabled: true }),
      pos({ stop_profit_enabled: false }),
      pos({}),
    ])
    expect(s.enabled + s.disabled + s.unknown).toBe(s.total)
  })
})

describe('summarizeGridSessions（会话级网格开关聚合）', () => {
  it('空会话返回全零', () => {
    expect(summarizeGridSessions([])).toEqual({ total: 0, enabled: 0, paused: 0 })
  })

  it('enabled 缺失按启用处理（与后端 DEFAULT 1 一致）', () => {
    const s = summarizeGridSessions([session({}), session({})])
    expect(s.enabled).toBe(2)
    expect(s.paused).toBe(0)
  })

  it('只有显式 false 才算暂停', () => {
    const s = summarizeGridSessions([
      session({ enabled: true }),
      session({ enabled: false }),
      session({}),
    ])
    expect(s).toEqual({ total: 3, enabled: 2, paused: 1 })
  })

  it('enabled + paused 恒等于 total', () => {
    const s = summarizeGridSessions([
      session({ enabled: false }), session({ enabled: false }), session({ enabled: true }),
    ])
    expect(s.enabled + s.paused).toBe(s.total)
  })
})

describe('chainEffective（门控链）', () => {
  it('全部开启 → 放行', () => {
    expect(chainEffective(true, true)).toBe(true)
  })

  it('任一级关闭 → 阻断', () => {
    expect(chainEffective(false, true)).toBe(false)
    expect(chainEffective(true, false)).toBe(false)
  })

  it('关闭优先于未知：有 false 就是 false，不受 null 干扰', () => {
    expect(chainEffective(null, false)).toBe(false)
    expect(chainEffective(false, null)).toBe(false)
  })

  it('无 false 但有未知 → 结果未知，不断言策略在运行', () => {
    expect(chainEffective(true, null)).toBeNull()
    expect(chainEffective(null, null)).toBeNull()
  })

  it('支持三级链', () => {
    expect(chainEffective(true, true, true)).toBe(true)
    expect(chainEffective(true, true, false)).toBe(false)
    expect(chainEffective(true, true, null)).toBeNull()
  })
})
