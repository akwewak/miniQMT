import type { PositionMetrics, RawPositionMetrics } from '../types'

const EMPTY: PositionMetrics = {
  total_market_value: 0,
  total_profit: 0,
  total_profit_ratio: 0,
  position_count: 0,
  stock_count: 0,
}

/**
 * 归一化后端持仓汇总指标。
 *
 * 两个后端的口径不一致，必须在此收口：
 * - Flask  utils.calculate_position_metrics() 返回 `profit_ratio`，小数（0.0523）
 * - 网关   server.py flask_positions() 返回 `total_profit_ratio`，同为小数
 * 而单只持仓的 `profit_ratio` 后端已乘 100（position_manager.py），是百分比数。
 *
 * 统一出口：`total_profit_ratio` 为百分比数（5.23 表示 5.23%），
 * 与单只持仓的 profit_ratio 口径一致，组件层可直接交给 fmtPercent。
 */
export function normalizeMetrics(raw: RawPositionMetrics | null | undefined): PositionMetrics {
  if (!raw) return { ...EMPTY }

  const ratioDecimal = num(raw.total_profit_ratio ?? raw.profit_ratio)
  const count = num(raw.position_count ?? raw.total_positions)

  return {
    total_market_value: num(raw.total_market_value),
    total_profit: num(raw.total_profit),
    total_profit_ratio: ratioDecimal * 100,
    position_count: count,
    stock_count: num(raw.stock_count ?? raw.position_count ?? raw.total_positions),
  }
}

function num(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}
