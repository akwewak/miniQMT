/**
 * 数据新鲜度。
 *
 * 监控界面最危险的失效方式不是"没数据"，而是"显示着 10 分钟前的数据
 * 却看不出来"。所有数据块都应标注自己有多旧，超时后视觉降级。
 */

export type Freshness = 'fresh' | 'stale' | 'dead' | 'unknown'

/** 超过 stale 秒视为陈旧（黄），超过 dead 秒视为失联（红）。 */
export interface FreshnessThreshold {
  stale: number
  dead: number
}

export const DEFAULT_THRESHOLD: FreshnessThreshold = { stale: 30, dead: 90 }

export function ageSeconds(updatedAt: number, now = Date.now()): number | null {
  if (!updatedAt) return null
  return Math.max(0, Math.floor((now - updatedAt) / 1000))
}

export function freshnessOf(
  updatedAt: number,
  threshold: FreshnessThreshold = DEFAULT_THRESHOLD,
  now = Date.now(),
): Freshness {
  const age = ageSeconds(updatedAt, now)
  if (age === null) return 'unknown'
  if (age >= threshold.dead) return 'dead'
  if (age >= threshold.stale) return 'stale'
  return 'fresh'
}

/** 人类可读的相对时间：'12 秒前' / '3 分钟前' / '2 小时前'。 */
export function formatAge(updatedAt: number, now = Date.now()): string {
  const age = ageSeconds(updatedAt, now)
  if (age === null) return '从未更新'
  if (age < 60) return `${age} 秒前`
  if (age < 3600) return `${Math.floor(age / 60)} 分钟前`
  return `${Math.floor(age / 3600)} 小时前`
}

export function freshnessClass(f: Freshness): string {
  switch (f) {
    case 'fresh': return 'text-slate-400'
    case 'stale': return 'text-amber-600'
    case 'dead': return 'text-red-600'
    default: return 'text-slate-300'
  }
}
