import type { TradeRecord } from '../types'

export interface TradeGroup {
  /** 分组键：YYYY-MM-DD */
  date: string
  /** 展示标签：今天 / 昨天 / MM-DD */
  label: string
  trades: TradeRecord[]
}

function dateKey(ts: string | null | undefined): string {
  if (!ts) return ''
  return String(ts).replace('T', ' ').substring(0, 10)
}

/** 相对日期标签。today 可注入以便测试。 */
export function dayLabel(date: string, today = new Date()): string {
  if (!date) return '未知日期'
  const t = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const todayKey = fmtKey(t)
  const yesterdayKey = fmtKey(new Date(t.getTime() - 86400000))
  if (date === todayKey) return '今天'
  if (date === yesterdayKey) return '昨天'
  return date.substring(5) // MM-DD
}

function fmtKey(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

/** 按交易日分组，日期倒序（新的在前）。 */
export function groupTradesByDay(trades: TradeRecord[], today = new Date()): TradeGroup[] {
  const buckets = new Map<string, TradeRecord[]>()
  for (const t of trades) {
    const key = dateKey(t.trade_time)
    if (!buckets.has(key)) buckets.set(key, [])
    buckets.get(key)!.push(t)
  }
  return [...buckets.entries()]
    .sort((a, b) => (a[0] < b[0] ? 1 : a[0] > b[0] ? -1 : 0))
    .map(([date, list]) => ({ date, label: dayLabel(date, today), trades: list }))
}

export interface TradeFilter {
  /** 股票代码/名称关键词 */
  keyword?: string
  direction?: 'ALL' | 'BUY' | 'SELL'
  strategy?: string
}

export function filterTrades(trades: TradeRecord[], f: TradeFilter): TradeRecord[] {
  const kw = (f.keyword || '').trim().toLowerCase()
  return trades.filter(t => {
    if (f.direction && f.direction !== 'ALL' && t.trade_type !== f.direction) return false
    if (f.strategy && f.strategy !== 'ALL' && t.strategy !== f.strategy) return false
    if (kw) {
      const hay = `${t.stock_code || ''} ${t.stock_name || ''}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
}
