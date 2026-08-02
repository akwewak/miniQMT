import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSystemStore } from './system'
import * as flaskApi from '../api/flask'

describe('system store 三态开关', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('初始状态全为 null（未知），不假装成"已关闭"', () => {
    const s = useSystemStore()
    expect(s.isMonitoring).toBeNull()
    expect(s.allowBuy).toBeNull()
    expect(s.simulationMode).toBeNull()
  })

  it('后端返回 null 时保持未知，而不是被 Boolean(null) 变成 false', async () => {
    vi.spyOn(flaskApi, 'getStatus').mockResolvedValue({
      account: null,
      settings: {
        isMonitoring: null, enableAutoTrading: null, enableGridTrading: null,
        allowBuy: null, allowSell: null, simulationMode: null, positionMonitorRunning: null,
      },
      isMonitoring: null,
    } as any)
    const s = useSystemStore()
    await s.fetchStatus()
    expect(s.isMonitoring).toBeNull()
    expect(s.autoTrading).toBeNull()
    expect(s.simulationMode).toBeNull()
  })

  it('后端返回真实布尔值时如实反映', async () => {
    vi.spyOn(flaskApi, 'getStatus').mockResolvedValue({
      account: null,
      settings: {
        isMonitoring: true, enableAutoTrading: false, enableGridTrading: true,
        allowBuy: true, allowSell: false, simulationMode: true, positionMonitorRunning: true,
      },
      isMonitoring: true,
    } as any)
    const s = useSystemStore()
    await s.fetchStatus()
    expect(s.isMonitoring).toBe(true)
    expect(s.autoTrading).toBe(false)
    expect(s.allowSell).toBe(false)
    expect(s.simulationMode).toBe(true)
  })

  it('settings 缺字段时该字段为 null 而非 false', async () => {
    vi.spyOn(flaskApi, 'getStatus').mockResolvedValue({
      account: null,
      settings: { isMonitoring: true },
      isMonitoring: true,
    } as any)
    const s = useSystemStore()
    await s.fetchStatus()
    expect(s.isMonitoring).toBe(true)
    expect(s.allowBuy).toBeNull()
  })

  it('fetchStatus 推进状态新鲜度时间戳', async () => {
    vi.spyOn(flaskApi, 'getStatus').mockResolvedValue({
      account: null, settings: {}, isMonitoring: null,
    } as any)
    const s = useSystemStore()
    expect(s.statusUpdatedAt).toBe(0)
    await s.fetchStatus()
    expect(s.statusUpdatedAt).toBeGreaterThan(0)
  })

  it('fetchConnection 更新连接状态与其独立时间戳', async () => {
    vi.spyOn(flaskApi, 'getConnectionStatus').mockResolvedValue(true)
    const s = useSystemStore()
    expect(s.connectionUpdatedAt).toBe(0)
    await s.fetchConnection()
    expect(s.connected).toBe(true)
    expect(s.connectionUpdatedAt).toBeGreaterThan(0)
  })

  it('QMT 掉线时 connected 能翻转为 false', async () => {
    const s = useSystemStore()
    vi.spyOn(flaskApi, 'getConnectionStatus').mockResolvedValue(true)
    await s.fetchConnection()
    expect(s.connected).toBe(true)

    vi.spyOn(flaskApi, 'getConnectionStatus').mockResolvedValue(false)
    await s.fetchConnection()
    expect(s.connected).toBe(false)
  })

  it('store 不再暴露任何写操作方法（只读保证）', () => {
    const s = useSystemStore() as any
    expect(s.toggleMonitor).toBeUndefined()
    expect(s.saveConfig).toBeUndefined()
  })
})
