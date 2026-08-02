import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as adapter from './adapter'
import * as flaskApi from './flask'
import * as xtquantApi from './xtquant'

/**
 * 只读契约守卫。
 *
 * web2.0 的定位是 monitor：不得存在任何写请求通道。
 * 这些用例在有人重新引入 POST/PUT/DELETE 时立即失败，
 * 让"去写化"是一个被持续保护的约束，而不是一次性的清理。
 */
describe('只读契约', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('adapter 不导出 apiPost 等写方法', () => {
    const mod = adapter as Record<string, unknown>
    expect(mod.apiGet).toBeTypeOf('function')
    expect(mod.apiPost).toBeUndefined()
    expect(mod.apiPut).toBeUndefined()
    expect(mod.apiDelete).toBeUndefined()
  })

  it('flask 客户端不再暴露任何写操作封装', () => {
    const banned = [
      'saveConfig', 'toggleMonitor', 'executeBuy', 'clearLogs', 'clearBuySellData',
      'importData', 'initHoldings', 'startGrid', 'stopGrid', 'setGridSessionEnabled',
      'setStopProfitEnabled', 'updateHoldings',
    ]
    for (const name of banned) {
      expect((flaskApi as Record<string, unknown>)[name], `flask.ts 不应导出 ${name}`).toBeUndefined()
    }
  })

  it('网关客户端不再暴露下单与开关封装', () => {
    const banned = ['placeXqOrder', 'toggleStopProfit', 'updateStopProfitConfig', 'cancelOrder']
    for (const name of banned) {
      expect((xtquantApi as Record<string, unknown>)[name], `xtquant.ts 不应导出 ${name}`).toBeUndefined()
    }
  })

  it('flask 客户端导出的每个函数都只发 GET 请求', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ status: 'success', data: [], sessions: [], success: true }),
    })) as any
    vi.stubGlobal('fetch', fetchMock)

    // 逐个调用所有导出函数，参数用最小可用值
    const args: Record<string, unknown[]> = {
      getMacdAdvice: ['000001.SZ'],
      getPositions: [0],
      getGridSession: ['000001.SZ'],
      getGridTrades: [1],
      getGridLedger: [1],
    }
    for (const [name, fn] of Object.entries(flaskApi)) {
      if (typeof fn !== 'function') continue
      await (fn as any)(...(args[name] || []))
    }

    expect(fetchMock).toHaveBeenCalled()
    for (const call of fetchMock.mock.calls) {
      const init = call[1] || {}
      const method = String(init.method || 'GET').toUpperCase()
      expect(method, `请求 ${call[0]} 使用了非 GET 方法`).toBe('GET')
      expect(init.body, `请求 ${call[0]} 携带了请求体`).toBeUndefined()
    }
  })

  it('网关客户端导出的每个函数都只发 GET 请求', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ success: true, data: { accounts: [] } }),
    })) as any
    vi.stubGlobal('fetch', fetchMock)

    for (const fn of Object.values(xtquantApi)) {
      if (typeof fn !== 'function') continue
      await (fn as any)()
    }

    expect(fetchMock).toHaveBeenCalled()
    for (const call of fetchMock.mock.calls) {
      const method = String((call[1] || {}).method || 'GET').toUpperCase()
      expect(method, `请求 ${call[0]} 使用了非 GET 方法`).toBe('GET')
    }
  })
})
