/**
 * Flask / 网关兼容端点的只读客户端。
 *
 * web2.0 的定位是 monitor —— 只读取并展示，不产生任何写操作。
 * 因此这里**只保留 GET**：不提供下单、配置保存、网格启停、初始化持仓等
 * 任何会改变后端状态的封装，从源头杜绝误触发。
 */
import { apiGet } from './adapter'

export async function getStatus() {
  const r = await apiGet('/api/status')
  if (!r || r.status !== 'success') return null
  return { account: r.account, settings: r.settings, isMonitoring: r.isMonitoring }
}

export async function getMacdAdvice(code: string) {
  return await apiGet(`/api/macd/advice?code=${encodeURIComponent(code)}`)
}

export async function getConfig() {
  const r = await apiGet('/api/config')
  if (!r || r.status !== 'success') return null
  return { data: r.data, ranges: r.ranges }
}

export async function getPositions(version = -1) {
  const r = await apiGet(`/api/positions?version=${version}`)
  if (!r || r.status !== 'success') return null
  return {
    positions: r.data?.positions || [],
    metrics: r.data?.metrics || {},
    positionsAll: r.data?.positions_all || [],
    version: r.data_version || 0,
    noChange: r.no_change || false,
  }
}

export async function getTradeRecords() {
  const r = await apiGet('/api/trade-records')
  if (!r || r.status !== 'success') return []
  return r.data || []
}

/** 当日委托（含在途未成交）。监控视图靠它感知挂单中的止盈卖单。 */
export async function getOrders() {
  const r = await apiGet('/api/orders')
  if (!r || r.status !== 'success') return []
  return r.data || []
}

export async function getConnectionStatus() {
  const r = await apiGet('/api/connection/status')
  if (!r || r.status !== 'success') return false
  return r.connected
}

// ---- 网格交易（只读） ----

export async function getGridSession(stockCode: string) {
  return apiGet(`/api/grid/session/${stockCode}`)
}

export async function getAllGridSessions() {
  const r = await apiGet('/api/grid/sessions')
  if (!r?.success) return []
  return r.sessions || []
}

export async function getGridTrades(sessionId: number, limit = 20, offset = 0) {
  const r = await apiGet(`/api/grid/trades/${sessionId}?limit=${limit}&offset=${offset}`)
  if (!r?.success) return { trades: [], totalCount: 0, pagination: { limit, offset, has_more: false } }
  return {
    trades: r.trades || [],
    totalCount: r.total_count || 0,
    pagination: r.pagination || { limit, offset, has_more: false },
  }
}

export async function getGridLedger(sessionId: number, limit = 50, offset = 0) {
  const r = await apiGet(`/api/grid/ledger/${sessionId}?limit=${limit}&offset=${offset}`)
  if (!r?.success) {
    return {
      summary: null,
      lots: [],
      matches: [],
      trades: [],
      totalCount: 0,
      pagination: { limit, offset, has_more: false },
      error: r?.error || '账本数据不可用',
    }
  }
  return {
    session_id: r.session_id,
    session: r.session,
    current_price: r.current_price,
    summary: r.summary,
    lots: r.lots || [],
    matches: r.matches || [],
    trades: r.trades || [],
    totalCount: r.total_count || 0,
    pagination: r.pagination || { limit, offset, has_more: false },
  }
}

export async function getGridRiskTemplates() {
  const r = await apiGet('/api/grid/risk-templates')
  if (!r?.success) return {}
  return r.templates || {}
}
