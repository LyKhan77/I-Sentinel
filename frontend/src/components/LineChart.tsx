import { useEffect, useRef, useState } from 'react'

export type ChartPoint = { t: number; v: number }
export type ChartSeries = { key: string; label: string; color: string; points: ChartPoint[]; dashed?: boolean }
export const PALETTE = ['#6929c4', '#1192e8', '#005d5d', '#9f1853', '#fa4d56', '#570408']

const PAD = { l: 40, r: 12, t: 8, b: 22 }

/** 3–5 angka sumbu Y yang "bulat" (1/2/5 × 10^n). */
function ticks(lo: number, hi: number): number[] {
  const raw = (hi - lo) / 4 || 1
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const out: number[] = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Number(v.toFixed(6)))
  return out
}

type Props = {
  title: string; series: ChartSeries[]; from: number; to: number; bucketMs: number
  yMin?: number; yMax?: number; unit?: string; shaded?: { from: number; to: number }[]
  height?: number; refLine?: { v: number; label: string }; locale: string; testId?: string
  /** Desimal nilai di tooltip/aria (label sumbu Y tetap angka mentah); default 1. */
  digits?: number
  /** Garis vertikal penanda waktu (mis. waktu event yang sedang dibuka). */
  markers?: { t: number; label: string }[]
}

/** Grafik garis SVG ringan (tanpa dependensi): celah saat data kosong, arsir offline, tooltip hover. */
export default function LineChart({ title, series, from, to, bucketMs, yMin, yMax, unit = '', shaded = [],
  height = 180, refLine, locale, testId, digits = 1, markers = [] }: Props) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(600)
  const [hover, setHover] = useState<number | null>(null)

  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width)
      if (w > 0) setWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const values = [...series.flatMap((s) => s.points.map((p) => p.v)), ...(refLine ? [refLine.v] : [])]
  const lo = yMin ?? Math.min(0, ...values)
  const top = values.length ? Math.max(...values) : lo + 1
  const hi = yMax ?? (top <= lo ? lo + 1 : top * 1.1)
  const w = Math.max(1, width - PAD.l - PAD.r)
  const h = height - PAD.t - PAD.b
  const span = to - from || 1
  const x = (t: number) => PAD.l + ((t - from) / span) * w
  const y = (v: number) => PAD.t + h - ((Math.min(Math.max(v, lo), hi) - lo) / (hi - lo || 1)) * h

  const path = (points: ChartPoint[]) => {
    let d = ''
    let prev: number | null = null
    for (const p of points) {
      d += `${prev === null || p.t - prev > bucketMs * 1.5 ? 'M' : 'L'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`
      prev = p.t
    }
    return d
  }
  // titik tanpa tetangga dalam 1,5 bucket (sebelum & sesudah) tidak punya segmen garis → gambar sebagai dot
  const isolated = (points: ChartPoint[]) => points.filter((p, i) =>
    (i === 0 || p.t - points[i - 1].t > bucketMs * 1.5)
    && (i === points.length - 1 || points[i + 1].t - p.t > bucketMs * 1.5))
  const fmtTime = (t: number) => new Date(t).toLocaleString(locale, span > 26 * 3600e3
    ? { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }
    : { hour: '2-digit', minute: '2-digit' })
  const nearest = (s: ChartSeries, t: number) => {
    let best: ChartPoint | null = null
    for (const p of s.points) if (!best || Math.abs(p.t - t) < Math.abs(best.t - t)) best = p
    return best && Math.abs(best.t - t) <= bucketMs ? best : null
  }
  const fmtV = (v: number) => `${v.toFixed(digits)}${unit}`
  const aria = `${title}: ${series.map((s) => {
    const last = s.points.at(-1)
    return `${s.label} ${last ? fmtV(last.v) : '—'}`
  }).join(', ')}`

  return (
    <div className="lc" ref={ref} data-testid={testId}>
      <svg width={width} height={height} role="img" aria-label={aria}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          const t = from + ((e.clientX - r.left - PAD.l) / w) * span
          setHover(t < from || t > to ? null : t)
        }}
        onMouseLeave={() => setHover(null)}>
        {shaded.map((r, i) => {
          const a = x(Math.max(r.from, from))
          const b = x(Math.min(r.to, to))
          return b >= a ? (
            <rect key={i} className="lc__offline" data-testid="lc-offline" x={a} y={PAD.t} width={Math.max(2, b - a)} height={h} />
          ) : null
        })}
        {ticks(lo, hi).map((v) => (
          <g key={v}>
            <line className="lc__grid" x1={PAD.l} x2={PAD.l + w} y1={y(v)} y2={y(v)} />
            <text className="lc__label" x={PAD.l - 6} y={y(v) + 4} textAnchor="end">{v}</text>
          </g>
        ))}
        {[0, 1, 2, 3, 4].map((i) => {
          const t = from + (span * i) / 4
          return (
            <text key={i} className="lc__label" x={x(t)} y={height - 6}
              textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'}>{fmtTime(t)}</text>
          )
        })}
        {series.map((s) => (
          <g key={s.key}>
            <path data-testid={`lc-line-${s.key}`} d={path(s.points)} fill="none" stroke={s.color}
              strokeWidth={1.5} strokeDasharray={s.dashed ? '4 3' : undefined} />
            {isolated(s.points).map((p) => (
              <circle key={p.t} data-testid={`lc-dot-${s.key}`} cx={x(p.t)} cy={y(p.v)} r={2.5} fill={s.color} />
            ))}
          </g>
        ))}
        {refLine && (
          <line data-testid="lc-ref" className="lc__ref" x1={PAD.l} x2={PAD.l + w} y1={y(refLine.v)} y2={y(refLine.v)}
            strokeDasharray="4 3" />
        )}
        {markers.filter((m) => m.t >= from && m.t <= to).map((m, i) => (
          <g key={i} data-testid="lc-marker">
            <title>{m.label}</title>
            <line className="lc__marker" x1={x(m.t)} x2={x(m.t)} y1={PAD.t} y2={PAD.t + h} />
          </g>
        ))}
        {hover !== null && <line className="lc__cursor" x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={PAD.t + h} />}
      </svg>
      {hover !== null && (
        <div className="lc__tip" data-testid="lc-tip" style={{ left: Math.max(0, Math.min(x(hover) + 8, width - 170)) }}>
          <div className="lc__tip-time">{fmtTime(hover)}</div>
          {series.map((s) => {
            const p = nearest(s, hover)
            return p && (
              <div key={s.key}><span className="lc__swatch" style={{ background: s.color }} />{s.label}: {fmtV(p.v)}</div>
            )
          })}
          {refLine && <div><span className="lc__swatch lc__swatch--ref" />{refLine.label}: {fmtV(refLine.v)}</div>}
        </div>
      )}
    </div>
  )
}
