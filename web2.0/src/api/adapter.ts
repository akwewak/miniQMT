import { getFlaskUrl, getXtquantUrl, getApiToken, loadConnection, getCurrentAccountId } from './accounts'

/**
 * 只读 HTTP 适配层。
 *
 * 刻意只导出 apiGet：web2.0 是纯监控端，不应存在任何写请求通道。
 * 需要下单/改配置请使用 web1.0（Flask 直连，仅绑本机）。
 */
export async function apiGet(path: string): Promise<any> {
  const url = resolveUrl(path)
  const headers: Record<string, string> = {}
  const token = getApiToken()
  if (token) headers['X-API-Token'] = token
  const accountId = getCurrentAccountId()
  if (accountId) headers['X-Account-Id'] = accountId
  try {
    const resp = await fetch(url, { headers })
    if (!resp.ok) return { status: 'error', error: `HTTP ${resp.status}` }
    const data = await resp.json()
    // 标准化 xtquant_manager ApiResponse (success: bool) → Flask 格式 (status: string)
    return normalizeResponse(data)
  } catch (e: any) {
    return { status: 'error', error: e.message || 'Network error' }
  }
}

function normalizeResponse(data: any): any {
  // xtquant_manager ApiResponse 使用 success: bool，Flask 使用 status: "success"/"error"
  // 统一转换为 Flask 兼容格式，确保 r.status !== 'success' 检查正确
  if (data && typeof data.success === 'boolean' && !data.status) {
    data.status = data.success ? 'success' : 'error'
  }
  return data
}

function resolveUrl(path: string): string {
  const conn = loadConnection()
  // xtquant 网关模式：所有请求统一走网关（不区分 /api/ 还是 /api/v1/）
  if (conn.mode === 'xtquant') {
    const base = getXtquantUrl()
    return `${base}${path}`
  }
  // /api/v1/ 路径强制走 xtquant（不受 mode 限制）
  if (path.startsWith('/api/v1/')) {
    const base = getXtquantUrl()
    return `${base}${path}`
  }
  // auto 模式：检测是否在 xtquant_manager 同源下运行
  if (conn.mode === 'auto') {
    const xtquantBase = getXtquantUrl()
    if (xtquantBase && window.location.origin === xtquantBase) {
      return `${xtquantBase}${path}`
    }
  }
  // Flask 直连模式：走对应账号的 Flask 实例
  const base = getFlaskUrl()
  if (base) return `${base}${path}`
  // 无 Flask URL → 同源（Vite dev proxy 或反向代理）
  return path
}
