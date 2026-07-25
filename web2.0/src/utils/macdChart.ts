// MACD 迷你全景图 SVG 渲染(蜡烛+MA8/MA34+MACD+底仓/网格区间带)。
// 与 web1.0/script.js 的 renderMacdChartSVG 逻辑保持一致。

export interface MacdBar {
  d: string
  o: number; h: number; l: number; c: number
  dif: number | null; dea: number | null; hist: number | null
  ma8: number | null; ma34: number | null
  cat: number
}

export function renderMacdChartSVG(series: MacdBar[]): string {
  if (!series || series.length < 2) return ''
  const W = 440, H = 244, padR = 4, plotL = 30 // plotL 左侧留给图例
  const n = series.length, plotW = W - plotL - padR, slot = plotW / n
  const bw = Math.max(1.2, slot * 0.6)
  const kTop = 6, kBot = 116, mTop = 126, mBot = 194, mMid = (mTop + mBot) / 2
  const ribTop = 200, ribH = 18
  let pMin = Infinity, pMax = -Infinity
  series.forEach(b => {
    pMin = Math.min(pMin, b.l); pMax = Math.max(pMax, b.h)
    ;[b.ma8, b.ma34].forEach(v => { if (v != null) { pMin = Math.min(pMin, v); pMax = Math.max(pMax, v) } })
  })
  const pRange = (pMax - pMin) || 1
  const py = (v: number) => kBot - (v - pMin) / pRange * (kBot - kTop)
  let mAbs = 1e-6
  series.forEach(b => (['dif', 'dea', 'hist'] as const).forEach(k => { if (b[k] != null) mAbs = Math.max(mAbs, Math.abs(b[k] as number)) }))
  const my = (v: number) => mMid - (v / mAbs) * ((mBot - mTop) / 2)
  const cx = (i: number) => plotL + i * slot + slot / 2
  const parts: string[] = []
  parts.push(`<line x1="${plotL}" y1="${mMid}" x2="${W - padR}" y2="${mMid}" stroke="#ccc" stroke-width="0.6" stroke-dasharray="3 3"/>`)
  // 蜡烛(红涨绿跌)
  series.forEach((b, i) => {
    const x = cx(i), col = b.c >= b.o ? '#e23c3c' : '#1ba15a'
    parts.push(`<line x1="${x.toFixed(1)}" y1="${py(b.h).toFixed(1)}" x2="${x.toFixed(1)}" y2="${py(b.l).toFixed(1)}" stroke="${col}" stroke-width="0.7"/>`)
    const y1 = py(b.o), y2 = py(b.c), top = Math.min(y1, y2), hgt = Math.max(0.8, Math.abs(y2 - y1))
    parts.push(`<rect x="${(x - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${hgt.toFixed(1)}" fill="${col}"/>`)
  })
  // 均线折线
  const maPath = (key: 'ma8' | 'ma34', col: string) => {
    let d = ''
    series.forEach((b, i) => { if (b[key] == null) return; d += (d ? 'L' : 'M') + cx(i).toFixed(1) + ' ' + py(b[key] as number).toFixed(1) + ' ' })
    return d ? `<path d="${d}" fill="none" stroke="${col}" stroke-width="1"/>` : ''
  }
  parts.push(maPath('ma34', '#8b5cf6'))
  parts.push(maPath('ma8', '#0891b2'))
  parts.push(`<text x="${plotL + 2}" y="${kTop + 9}" font-size="8" fill="#8b5cf6">MA34</text>`)
  parts.push(`<text x="${plotL + 30}" y="${kTop + 9}" font-size="8" fill="#0891b2">MA8</text>`)
  // MACD 柱
  series.forEach((b, i) => {
    if (b.hist == null) return
    const x = cx(i), y0 = my(0), yv = my(b.hist), top = Math.min(y0, yv), hgt = Math.max(0.6, Math.abs(yv - y0))
    parts.push(`<rect x="${(x - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${hgt.toFixed(1)}" fill="${b.hist >= 0 ? '#e23c3c' : '#1ba15a'}"/>`)
  })
  // DIF/DEA 折线
  const linePath = (key: 'dif' | 'dea', col: string) => {
    let d = ''
    series.forEach((b, i) => { if (b[key] == null) return; d += (d ? 'L' : 'M') + cx(i).toFixed(1) + ' ' + my(b[key] as number).toFixed(1) + ' ' })
    return d ? `<path d="${d}" fill="none" stroke="${col}" stroke-width="1"/>` : ''
  }
  parts.push(linePath('dif', '#2563eb'))
  parts.push(linePath('dea', '#f59e0b'))
  parts.push(`<text x="${plotL + 2}" y="${mTop + 9}" font-size="8" fill="#999">MACD</text>`)
  // 底仓/网格 区间带(左侧图例 + 段内简化文字)
  const BASE_COLOR = ['#b91c1c', '#d97706', '#d97706', '#6b7280']
  const BASE_TEXT = ['重仓', '半仓以下', '半仓以下', '清仓']
  const GRID_COLOR = ['#16a34a', '#16a34a', '#16a34a', '#9ca3af']
  const GRID_TEXT = ['启动', '启动', '启动', '停用']
  const ribbon = (y: number, colorArr: string[], textArr: string[], legend: string) => {
    let out = `<text x="2" y="${y + 12.5}" font-size="9" fill="#555">${legend}</text>`
    const segs: [number, number, number][] = []; let sidx = 0
    for (let i = 1; i <= n; i++) { if (i === n || series[i].cat !== series[sidx].cat) { segs.push([sidx, i - 1, series[sidx].cat]); sidx = i } }
    segs.forEach(([i0, i1, cat]) => {
      const x0 = plotL + i0 * slot, w = (i1 + 1 - i0) * slot
      out += `<rect x="${x0.toFixed(1)}" y="${y}" width="${w.toFixed(1)}" height="${ribH}" fill="${colorArr[cat]}" opacity="0.92"/>`
      if (w >= 30) out += `<text x="${(x0 + w / 2).toFixed(1)}" y="${y + 12.5}" font-size="9" fill="#fff" text-anchor="middle">${textArr[cat]}</text>`
    })
    return out
  }
  parts.push(ribbon(ribTop, BASE_COLOR, BASE_TEXT, '底仓'))
  parts.push(ribbon(ribTop + ribH + 2, GRID_COLOR, GRID_TEXT, '网格'))
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" xmlns="http://www.w3.org/2000/svg" style="display:block">${parts.join('')}</svg>`
}
