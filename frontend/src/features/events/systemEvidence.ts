import type { TKey } from '../../app/i18n'
import type { EventOut } from '../../api/events'
import type { HistPoint, NodeHistory } from '../../api/monitoring'

/** Retensi `monitoring_sample` — di luar ini tidak ada tren untuk digambar. */
export const EVIDENCE_RETENTION_MS = 7 * 24 * 3_600_000
/** Batas jendela `GET /monitoring/history?from&to` (422 di atas ini). */
export const MAX_WINDOW_MS = 6 * 3_600_000

const MIN = 60_000
const HEALTH_KEYS = ['node_cpu', 'node_ram', 'infer_latency', 'mqtt_backlog', 'gpu_temp', 'gpu_vram',
  'camera_no_frames', 'camera_low_fps'] as const
const CAUSES: Record<string, TKey> = {
  timeout: 'events.evidence.cause.timeout',
  lwt: 'events.evidence.cause.lwt',
  online: 'events.evidence.cause.online',
}

export type ChartSeriesSpec = { key: string; labelKey: TKey; pick: (n: NodeHistory) => { t: number; v: number }[] }
export type ChartSpec = {
  key: string
  titleKey: TKey
  unit: string
  yMin?: number
  series: ChartSeriesSpec[]
  refLine?: { v: number; labelKey: TKey }
}
export type Evidence = {
  kind: 'health' | 'node' | 'unknown'
  expired: boolean
  nodeId: number | null
  window: { from: number; to: number } | null
  facts: { labelKey: TKey; value: string }[]
  charts: ChartSpec[]
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null)

/** Angka gaya backend `_fmt`: bulat bila utuh, satu desimal bila tidak. */
const fmtNum = (v: number | null, unit = ''): string =>
  v == null ? '—' : `${Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1)}${unit}`

const pts = (rows: HistPoint[] | undefined, kind: 'avg' | 'max' | 'min') =>
  (rows ?? []).flatMap((p) => {
    const v = p[kind]
    return typeof v === 'number' ? [{ t: Date.parse(p.t), v }] : []
  })

const targetPart = (target: unknown, prefix: string): number | null => {
  const s = str(target)
  if (!s?.startsWith(`${prefix}:`)) return null
  const parts = s.slice(prefix.length + 1).split(':')
  const n = Number(parts[parts.length - 1])
  return Number.isInteger(n) ? n : null
}

const camOf = (n: NodeHistory, id: number | null) => n.cameras.find((c) => c.id === id)
const camPts = (kind: 'frame_age_s' | 'fps', agg: 'max' | 'min') =>
  (id: number | null) => (n: NodeHistory) => pts(camOf(n, id)?.[kind], agg)

/** Jendela tren: mengikuti durasi alert bila diketahui, selalu dibatasi MAX_WINDOW_MS dari sisi awal. */
export function evidenceWindow(e: EventOut, now: number): { from: number; to: number } {
  const ts = Date.parse(e.ts_event)
  const p = e.payload ?? {}
  const lasted = num(p.lasted_min)
  const health = p.kind === 'health'
  const online = !health && p.reason === 'online'
  const lead = health && p.state === 'resolved' && !p.closed && lasted != null ? lasted + 15 : 30
  const tail = online || (health && lasted != null) ? 15 : 30
  const to = Math.min(now, ts + tail * MIN)
  const from = Math.max(ts - lead * MIN, to - MAX_WINDOW_MS)
  return { from, to }
}

function healthFacts(p: Record<string, unknown>, t: (k: TKey) => string): { labelKey: TKey; value: string }[] {
  const unit = str(p.unit) ?? ''
  const lasting = num(p.lasted_min)
  const status = p.closed ? t('events.evidence.closed')
    : lasting != null ? t('events.evidence.resolved').replace('{n}', String(Math.round(lasting)))
      : p.state === 'resolved' ? t('events.evidence.resolvedNoDuration') : t('events.evidence.firing')
  const duration = num(p.duration_min)
  return [
    { labelKey: 'events.evidence.rule', value: t(`health.rule.${p.rule}` as TKey) },
    { labelKey: 'events.evidence.target', value: str(p.label) ?? '—' },
    { labelKey: 'events.evidence.value', value: fmtNum(num(p.value), unit) },
    { labelKey: 'events.evidence.threshold', value: fmtNum(num(p.threshold), unit) },
    { labelKey: 'events.evidence.durationRule', value: duration == null ? '—' : t('events.evidence.minutes').replace('{n}', String(duration)) },
    { labelKey: 'events.evidence.status', value: status },
  ]
}

function nodeFacts(p: Record<string, unknown>, t: (k: TKey) => string): { labelKey: TKey; value: string }[] {
  const cause = CAUSES[str(p.reason) ?? '']
  return [
    { labelKey: 'events.evidence.node', value: str(p.node) ?? '—' },
    { labelKey: 'events.evidence.cause', value: cause ? t(cause) : '—' },
    { labelKey: 'events.evidence.status', value: t(p.reason === 'online' ? 'events.evidence.statusOnline' : 'events.evidence.statusOffline') },
  ]
}

/** Peta rule → grafik: agregat harus sama dengan yang dipakai pengecekan alert di backend. */
function healthCharts(p: Record<string, unknown>): ChartSpec[] {
  const threshold = num(p.threshold)
  const ref = threshold == null ? undefined : { v: threshold, labelKey: 'events.evidence.threshold' as TKey }
  const seq = (rule: string, seriesKey: string, titleKey: TKey, unit: string, kind: 'avg' | 'max' | 'min', yMin?: number): ChartSpec => ({
    key: rule, titleKey, unit, yMin, refLine: ref,
    series: [{ key: seriesKey, labelKey: `events.evidence.series.${kind}` as TKey,
      pick: (n) => pts(n.series[seriesKey as keyof NodeHistory['series']] as HistPoint[] | undefined, kind) }],
  })
  switch (p.rule) {
    case 'node_cpu':
      return [seq('node_cpu', 'cpu_pct', 'events.evidence.chart.cpu', '%', 'avg', 0)]
    case 'node_ram':
      return [seq('node_ram', 'ram_pct', 'events.evidence.chart.ram', '%', 'avg', 0)]
    case 'infer_latency':
      return [{
        key: 'infer_latency', titleKey: 'events.evidence.chart.latency', unit: str(p.unit) ?? 'ms', refLine: ref,
        series: [
          { key: 'ms_avg', labelKey: 'events.evidence.series.avg', pick: (n) => pts(n.series.ms_avg, 'avg') },
          { key: 'ms_max', labelKey: 'events.evidence.series.max', pick: (n) => pts(n.series.ms_max, 'max') },
        ],
      }]
    case 'mqtt_backlog':
      return [seq('mqtt_backlog', 'mqtt_backlog', 'events.evidence.chart.backlog', '', 'max', 0)]
    case 'gpu_temp': {
      const gi = targetPart(p.target, 'gpu')
      const rows = (n: NodeHistory) => pts(n.series.gpus[String(gi)]?.temp_c, 'max')
      return [{ key: 'gpu_temp', titleKey: 'events.evidence.chart.gpuTemp', unit: str(p.unit) ?? '°C', refLine: ref,
        series: [{ key: 'gpu_temp', labelKey: 'events.evidence.series.max', pick: rows }] }]
    }
    case 'gpu_vram': {
      const gi = targetPart(p.target, 'gpu')
      const rows = (n: NodeHistory) => pts(n.series.gpus[String(gi)]?.vram_pct, 'max')
      return [{ key: 'gpu_vram', titleKey: 'events.evidence.chart.gpuVram', unit: str(p.unit) ?? '%', refLine: ref,
        series: [{ key: 'gpu_vram', labelKey: 'events.evidence.series.max', pick: rows }] }]
    }
    case 'camera_no_frames': {
      const ci = targetPart(p.target, 'cam')
      return [{ key: 'camera_no_frames', titleKey: 'events.evidence.chart.frameAge', unit: str(p.unit) ?? 's', yMin: 0,
        refLine: ref, series: [{ key: 'camera_no_frames', labelKey: 'events.evidence.series.max', pick: camPts('frame_age_s', 'max')(ci) }] }]
    }
    case 'camera_low_fps': {
      const ci = targetPart(p.target, 'cam')
      // alert memakai persen terhadap target FPS, bukan FPS mentah
      const rows = (n: NodeHistory) => {
        const target = camOf(n, ci)?.target_fps
        if (!target) return []
        return pts(camOf(n, ci)?.fps, 'min').map((p) => ({ t: p.t, v: Math.round((p.v / target) * 1000) / 10 }))
      }
      return [{ key: 'camera_low_fps', titleKey: 'events.evidence.chart.lowFps', unit: str(p.unit) ?? '%', yMin: 0,
        refLine: ref, series: [{ key: 'camera_low_fps', labelKey: 'events.evidence.series.min', pick: rows }] }]
    }
    default:
      return []
  }
}

const nodeCharts = (): ChartSpec[] => [
  { key: 'node_cpu_offline', titleKey: 'events.evidence.chart.cpu', unit: '%', yMin: 0,
    series: [{ key: 'cpu_pct', labelKey: 'events.evidence.series.avg', pick: (n) => pts(n.series.cpu_pct, 'avg') }] },
  { key: 'node_fps_offline', titleKey: 'events.evidence.chart.inferFps', unit: 'fps', yMin: 0,
    series: [{ key: 'infer_fps', labelKey: 'events.evidence.series.avg', pick: (n) => pts(n.series.infer_fps, 'avg') }] },
]

/**
 * Fakta, jendela, dan grafik dari payload event system. Fungsi murni: `now` dikirim pemanggil
 * supaya tidak ada `Date.now()` di badan render.
 */
export function systemEvidence(e: EventOut, t: (k: TKey) => string, now: number): Evidence {
  const p = e.payload ?? {}
  const ts = Date.parse(e.ts_event)
  const isHealth = p.kind === 'health' && str(p.rule) != null
  const isNode = !isHealth && str(p.node) != null && p.reason !== undefined
  const kind: Evidence['kind'] = isHealth ? 'health' : isNode ? 'node' : 'unknown'
  const facts = isHealth ? healthFacts(p, t)
    : isNode ? nodeFacts(p, t)
      : []
  // rule tak dikenal tetap pegang fakta, hanya grafiknya yang tidak bisa dipetakan
  const charts = isHealth && HEALTH_KEYS.includes(str(p.rule) as (typeof HEALTH_KEYS)[number]) ? healthCharts(p)
    : isNode ? nodeCharts()
      : []
  const expired = now - ts > EVIDENCE_RETENTION_MS
  const nodeId = typeof e.node_id === 'number' ? e.node_id : null
  return {
    kind,
    expired,
    nodeId,
    window: kind === 'unknown' || expired ? null : evidenceWindow(e, now),
    facts,
    // grafik butuh node konkret: tanpa node_id tidak ada deret yang bisa diambil
    charts: expired || nodeId == null ? [] : charts,
  }
}
