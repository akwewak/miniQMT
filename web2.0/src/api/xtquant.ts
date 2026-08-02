/**
 * xtquant_manager 网关 v1 API 的只读客户端。
 *
 * 与 flask.ts 一样只保留 GET：网关虽有下单/止盈开关等写接口，
 * 但 web2.0 是纯监控端，不在此暴露任何调用入口。
 */
import { apiGet } from './adapter'
import { getCurrentAccountId } from './accounts'

function aid(): string { return getCurrentAccountId() }

export async function getAccountIds() {
  const r = await apiGet('/api/v1/accounts')
  if (!r?.success) return []
  return r.data?.accounts || []
}

export async function getAccountStatus(accountId?: string) {
  const r = await apiGet(`/api/v1/accounts/${accountId || aid()}/status`)
  return r?.data || {}
}

export async function getXqAsset(accountId?: string) {
  return (await apiGet(`/api/v1/accounts/${accountId || aid()}/asset`))?.data || {}
}

export async function getXqHealth() {
  return (await apiGet('/api/v1/health'))?.data || {}
}

/** 动态止盈止损运行状态（只读展示，不提供切换入口）。 */
export async function getStopProfitStatus() {
  return (await apiGet('/api/v1/stop-profit/status'))?.data || {}
}
