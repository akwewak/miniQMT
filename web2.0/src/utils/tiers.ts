import type { Position, GridSession, TriState } from '../types'

/**
 * 三级开关聚合。
 *
 * 自动止盈止损与网格交易各有一条三级门控链，任何一级关闭则策略不产生新单：
 *
 *   动态止盈止损: ENABLE_AUTO_OPERATION → ENABLE_AUTO_TRADING → positions.stop_profit_enabled
 *   网格交易:     ENABLE_AUTO_OPERATION → ENABLE_GRID_TRADING → grid_trading_sessions.enabled
 *
 * 前两级是全局布尔（可能为 null=未知），第三级是逐个体的，需要聚合成计数。
 */

/** 个股级止盈开关的聚合计数 */
export interface StopProfitSummary {
  total: number
  enabled: number
  disabled: number
  /** 后端未提供该字段的持仓数（老库缺列时出现） */
  unknown: number
}

export function summarizeStopProfit(positions: Position[]): StopProfitSummary {
  const total = positions.length
  let enabled = 0
  let disabled = 0
  for (const p of positions) {
    if (p.stop_profit_enabled === true) enabled++
    else if (p.stop_profit_enabled === false) disabled++
  }
  return { total, enabled, disabled, unknown: total - enabled - disabled }
}

/** 会话级网格开关的聚合计数 */
export interface GridSessionSummary {
  total: number
  enabled: number
  paused: number
}

/**
 * 统计网格会话的启用/暂停数。
 *
 * `enabled` 缺失时按启用处理 —— 与后端 `grid_trading_sessions.enabled`
 * 的 DEFAULT 1 一致，只有显式 false 才算暂停。
 */
export function summarizeGridSessions(sessions: GridSession[]): GridSessionSummary {
  const total = sessions.length
  const paused = sessions.filter(s => s.enabled === false).length
  return { total, enabled: total - paused, paused }
}

/**
 * 整条门控链是否放行。
 *
 * 任一级为 false 即阻断；无 false 但有 null（未知）时结果也是 null——
 * 监控端不能因为"读不到"就断言策略在运行。
 */
export function chainEffective(...tiers: TriState[]): TriState {
  if (tiers.some(t => t === false)) return false
  if (tiers.some(t => t === null || t === undefined)) return null
  return true
}
