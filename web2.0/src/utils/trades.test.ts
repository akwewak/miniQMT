import { describe, it, expect } from 'vitest'
import { groupTradesByDay, filterTrades, dayLabel } from './trades'
import type { TradeRecord } from '../types'

const TODAY = new Date(2026, 7, 1) // 2026-08-01

function trade(over: Partial<TradeRecord> = {}): TradeRecord {
  return {
    stock_code: '000001',
    stock_name: '平安银行',
    trade_type: 'BUY',
    price: 10,
    volume: 100,
    trade_time: '2026-08-01 10:00:00',
    trade_id: 'T1',
    strategy: 'grid',
    ...over,
  }
}

describe('dayLabel', () => {
  it('当天显示"今天"', () => {
    expect(dayLabel('2026-08-01', TODAY)).toBe('今天')
  })

  it('前一天显示"昨天"', () => {
    expect(dayLabel('2026-07-31', TODAY)).toBe('昨天')
  })

  it('更早显示 MM-DD', () => {
    expect(dayLabel('2026-07-20', TODAY)).toBe('07-20')
  })

  it('跨月边界的昨天仍正确（8-01 的前一天是 7-31）', () => {
    expect(dayLabel('2026-07-31', new Date(2026, 7, 1))).toBe('昨天')
  })

  it('空日期不崩', () => {
    expect(dayLabel('', TODAY)).toBe('未知日期')
  })
})

describe('groupTradesByDay', () => {
  it('同一天的成交聚到一组', () => {
    const g = groupTradesByDay([
      trade({ trade_time: '2026-08-01 10:00:00' }),
      trade({ trade_time: '2026-08-01 14:30:00' }),
    ], TODAY)
    expect(g).toHaveLength(1)
    expect(g[0].trades).toHaveLength(2)
    expect(g[0].label).toBe('今天')
  })

  it('不同日期分成多组，且按日期倒序（新的在前）', () => {
    const g = groupTradesByDay([
      trade({ trade_time: '2026-07-20 10:00:00' }),
      trade({ trade_time: '2026-08-01 10:00:00' }),
      trade({ trade_time: '2026-07-31 10:00:00' }),
    ], TODAY)
    expect(g.map(x => x.date)).toEqual(['2026-08-01', '2026-07-31', '2026-07-20'])
    expect(g.map(x => x.label)).toEqual(['今天', '昨天', '07-20'])
  })

  it('兼容 ISO 带 T 的时间格式', () => {
    const g = groupTradesByDay([trade({ trade_time: '2026-08-01T09:31:00' })], TODAY)
    expect(g[0].date).toBe('2026-08-01')
  })

  it('空列表返回空数组', () => {
    expect(groupTradesByDay([], TODAY)).toEqual([])
  })
})

describe('filterTrades', () => {
  const list = [
    trade({ stock_code: '000001', stock_name: '平安银行', trade_type: 'BUY', strategy: 'grid' }),
    trade({ stock_code: '600036', stock_name: '招商银行', trade_type: 'SELL', strategy: 'stop_loss' }),
    trade({ stock_code: '000333', stock_name: '美的集团', trade_type: 'SELL', strategy: 'grid' }),
  ]

  it('无条件时全部返回', () => {
    expect(filterTrades(list, {})).toHaveLength(3)
  })

  it('按方向筛选', () => {
    expect(filterTrades(list, { direction: 'SELL' })).toHaveLength(2)
    expect(filterTrades(list, { direction: 'BUY' })).toHaveLength(1)
  })

  it('direction=ALL 等同于不筛选', () => {
    expect(filterTrades(list, { direction: 'ALL' })).toHaveLength(3)
  })

  it('按策略筛选', () => {
    expect(filterTrades(list, { strategy: 'grid' })).toHaveLength(2)
  })

  it('关键词匹配股票代码', () => {
    expect(filterTrades(list, { keyword: '600036' })).toHaveLength(1)
  })

  it('关键词匹配股票名称', () => {
    expect(filterTrades(list, { keyword: '美的' })).toHaveLength(1)
  })

  it('关键词大小写不敏感且忽略首尾空格', () => {
    const l = [trade({ stock_code: '000001.SZ', stock_name: 'PingAn' })]
    expect(filterTrades(l, { keyword: '  pingan  ' })).toHaveLength(1)
  })

  it('多条件是 AND 关系', () => {
    expect(filterTrades(list, { direction: 'SELL', strategy: 'grid' })).toHaveLength(1)
  })

  it('无匹配时返回空数组', () => {
    expect(filterTrades(list, { keyword: '不存在的股票' })).toEqual([])
  })
})
