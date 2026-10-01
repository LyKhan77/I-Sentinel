import { describe, expect, test } from 'vitest'
import { renderHook } from '@testing-library/react'
import type { EventOut } from '../api/events'
import type { NodeHistory } from '../api/monitoring'
import { EVIDENCE_RETENTION_MS, MAX_WINDOW_MS, evidenceWindow, systemEvidence } from '../features/events/systemEvidence'
import { I18nProvider, useT } from '../app/i18n'
import { getMonitoringHistoryWindow } from '../api/monitoring'

const MIN = 60_000
const HOUR = 3_600_000
const NOW = Date.UTC(2026, 9, 1, 8, 0)
const T = (ms: number) => new Date(ms).toISOString()

// penerjemah asli (locale id) — bukan peta palsu, supaya paritas kunci ikut teruji
const { result } = renderHook(() => useT(), { wrapper: I18nProvider })
const t = (k: Parameters<typeof result.current.t>[0]) => String(result.current.t(k))

function ev(tsMs: number, payload: Record<string, unknown>, extra: Partial<EventOut> = {}): EventOut {
  return {
    id: 1, event_id: 'ev-1', type: 'system', camera_id: null, zone_id: null, severity: 'warning',
    ts_event: T(tsMs), payload, clip_path: null, snapshot_path: null, ...extra,
  }
}

// --- jendela ---------------------------------------------------------------

describe('evidenceWindow', () => {
  test('firing: 30 menit sebelum event sampai min(now, +30 menit)', () => {
    const ts = NOW - 10 * MIN
    expect(evidenceWindow(ev(ts, { kind: 'health', rule: 'node_cpu', state: 'firing' }), NOW))
      .toEqual({ from: ts - 30 * MIN, to: NOW })
  })

  test('firing lama: batas atas ts + 30 menit bila sudah lewat', () => {
    const ts = NOW - 3 * HOUR
    expect(evidenceWindow(ev(ts, { kind: 'health', rule: 'node_cpu', state: 'firing' }), NOW))
      .toEqual({ from: ts - 30 * MIN, to: ts + 30 * MIN })
  })

  test('resolved dengan lasted_min: jendela mengikuti durasi alert', () => {
    const ts = NOW - 5 * MIN
    expect(evidenceWindow(ev(ts, { kind: 'health', rule: 'node_cpu', state: 'resolved', lasted_min: 10 }), NOW))
      .toEqual({ from: ts - 25 * MIN, to: NOW })
  })

  test('node online: dari ts − 30 menit sampai ts + 15 menit', () => {
    const ts = NOW - 20 * MIN
    expect(evidenceWindow(ev(ts, { node: 'edge-1', reason: 'online' }), NOW))
      .toEqual({ from: ts - 30 * MIN, to: ts + 15 * MIN })
  })

  test('closed diperlakukan seperti firing untuk jendela', () => {
    const ts = NOW - 2 * HOUR
    const closed = ev(ts, { kind: 'health', rule: 'node_cpu', state: 'resolved', closed: true })
    const firing = ev(ts, { kind: 'health', rule: 'node_cpu', state: 'firing' })
    expect(evidenceWindow(closed, NOW)).toEqual(evidenceWindow(firing, NOW))
  })

  test('jendela panjang dipotong tepat MAX_WINDOW_MS dari sisi awal', () => {
    const ts = NOW - 5 * MIN
    const { from, to } = evidenceWindow(ev(ts, { kind: 'health', rule: 'node_cpu', state: 'resolved', lasted_min: 600 }), NOW)
    expect(to).toBe(NOW)
    expect(to - from).toBe(MAX_WINDOW_MS)
  })
})

// --- fakta dan kedaluwarsa -------------------------------------------------

describe('systemEvidence', () => {
  test('event lebih tua dari retensi → expired, tanpa jendela dan grafik, fakta tetap', () => {
    const ts = NOW - EVIDENCE_RETENTION_MS - MIN
    const e = systemEvidence(ev(ts, { kind: 'health', rule: 'node_cpu', target: 'node:1', label: 'CPU node',
      value: 91.5, threshold: 90, unit: '%', duration_min: 5, state: 'firing' }, { node_id: 1 }), t, NOW)
    expect(e.expired).toBe(true)
    expect(e.window).toBeNull()
    expect(e.charts).toEqual([])
    expect(e.facts.length).toBeGreaterThan(0)
  })

  test('tepat di ambang retensi belum kedaluwarsa', () => {
    const ts = NOW - EVIDENCE_RETENTION_MS
    const e = systemEvidence(ev(ts, { kind: 'health', rule: 'node_cpu' }, { node_id: 1 }), t, NOW)
    expect(e.expired).toBe(false)
    expect(e.window).not.toBeNull()
  })

  test('fakta health: aturan, target, nilai, ambang, durasi aturan, status', () => {
    const ts = NOW - 10 * MIN
    const e = systemEvidence(ev(ts, { kind: 'health', rule: 'node_cpu', target: 'node:1', label: 'Server',
      value: 91.5, threshold: 90, unit: '%', duration_min: 5, state: 'firing' }, { node_id: 1 }), t, NOW)
    expect(e.kind).toBe('health')
    const vals = Object.fromEntries(e.facts.map((f) => [f.labelKey, f.value]))
    expect(vals['events.evidence.rule']).toBe(t('health.rule.node_cpu'))
    expect(vals['events.evidence.target']).toBe('Server')
    expect(vals['events.evidence.value']).toBe('91.5%')
    expect(vals['events.evidence.threshold']).toBe('90%')
    expect(vals['events.evidence.durationRule']).toBe('5 mnt')
    expect(vals['events.evidence.status']).toBe(t('events.evidence.firing'))
  })

  test('status resolved memakai lasted_min; closed memakai label ditutup', () => {
    const resolved = systemEvidence(ev(NOW - MIN, { kind: 'health', rule: 'node_cpu', state: 'resolved', lasted_min: 12 }), t, NOW)
    expect(resolved.facts.find((f) => f.labelKey === 'events.evidence.status')?.value).toBe('Pulih · selama 12 mnt')
    const closed = systemEvidence(ev(NOW - MIN, { kind: 'health', rule: 'node_cpu', state: 'resolved', closed: true }), t, NOW)
    expect(closed.facts.find((f) => f.labelKey === 'events.evidence.status')?.value).toBe('Ditutup')
    const noDur = systemEvidence(ev(NOW - MIN, { kind: 'health', rule: 'node_cpu', state: 'resolved' }), t, NOW)
    expect(noDur.facts.find((f) => f.labelKey === 'events.evidence.status')?.value).toBe('Pulih')
  })

  test('field hilang → "—" (fakta tetap tampil)', () => {
    const e = systemEvidence(ev(NOW - MIN, { kind: 'health', rule: 'node_cpu' }), t, NOW)
    const vals = Object.fromEntries(e.facts.map((f) => [f.labelKey, f.value]))
    expect(vals['events.evidence.target']).toBe('—')
    expect(vals['events.evidence.value']).toBe('—')
  })

  test('fakta node: node, penyebab, status', () => {
    const causes = { timeout: 'Heartbeat berhenti', lwt: 'Koneksi MQTT node terputus', online: 'Node kembali online' }
    for (const [reason, want] of Object.entries(causes)) {
      const e = systemEvidence(ev(NOW - MIN, { node: 'edge-1', reason }), t, NOW)
      expect(e.kind).toBe('node')
      expect(e.facts.find((f) => f.labelKey === 'events.evidence.node')?.value).toBe('edge-1')
      expect(e.facts.find((f) => f.labelKey === 'events.evidence.cause')?.value).toBe(want)
    }
  })

  test('payload health/node tak valid → unknown tanpa fakta', () => {
    expect(systemEvidence(ev(NOW - MIN, {}), t, NOW)).toMatchObject({ kind: 'unknown', facts: [], charts: [] })
    expect(systemEvidence(ev(NOW - MIN, { kind: 'health' }), t, NOW).kind).toBe('unknown')
    expect(systemEvidence(ev(NOW - MIN, { node: 'x' }), t, NOW).kind).toBe('unknown')
  })

  test('node_id null dipertahankan sebagai null', () => {
    expect(systemEvidence(ev(NOW - MIN, { kind: 'health', rule: 'node_cpu' }), t, NOW).nodeId).toBeNull()
    expect(systemEvidence(ev(NOW - MIN, { kind: 'health', rule: 'node_cpu' }, { node_id: 4 }), t, NOW).nodeId).toBe(4)
  })
})

// --- pemetaan grafik per rule ----------------------------------------------

const point = (m: number, v: number) => ({ t: T(NOW - m * MIN), avg: v })

function node(over: Partial<NodeHistory> = {}): NodeHistory {
  return {
    id: 1, name: 'server',
    series: { cpu_pct: [], ram_pct: [], ms_avg: [], ms_max: [], infer_fps: [], mqtt_backlog: [], gpus: {} },
    cameras: [], offline: [], ...over,
  }
}

const HEAD = (rule: string, payload: Record<string, unknown> = {}, ts = NOW - 10 * MIN) =>
  ev(ts, { kind: 'health', rule, label: 'Server', value: 1, threshold: 90, unit: '%', duration_min: 5,
    state: 'firing', ...payload }, { node_id: 1 })

function chartOf(e: ReturnType<typeof systemEvidence>, key: string) {
  const c = e.charts.find((x) => x.key === key)
  if (!c) throw new Error(`no chart ${key}`)
  return c
}

describe('systemEvidence chart mapping', () => {
  test('node_cpu: satu seri cpu_pct avg + garis ambang', () => {
    const c = chartOf(systemEvidence(HEAD('node_cpu'), t, NOW), 'node_cpu')
    expect(c.series).toHaveLength(1)
    expect(c.series[0].pick(node({ series: { ...node().series, cpu_pct: [{ t: T(NOW), avg: 91, max: 99 }] } })))
      .toEqual([{ t: Date.parse(T(NOW)), v: 91 }])
    expect(c.refLine?.v).toBe(90)
  })

  test('node_ram memakai ram_pct avg', () => {
    const c = chartOf(systemEvidence(HEAD('node_ram'), t, NOW), 'node_ram')
    expect(c.series[0].pick(node({ series: { ...node().series, ram_pct: [{ t: T(NOW), avg: 77.5 }] } })))
      .toEqual([{ t: Date.parse(T(NOW)), v: 77.5 }])
  })

  test('infer_latency: dua seri (avg dan max)', () => {
    const c = chartOf(systemEvidence(HEAD('infer_latency'), t, NOW), 'infer_latency')
    expect(c.series).toHaveLength(2)
    const nh = node({ series: { ...node().series, ms_avg: [{ t: T(NOW), avg: 120 }], ms_max: [{ t: T(NOW), max: 300 }] } })
    expect(c.series[0].pick(nh)).toEqual([{ t: Date.parse(T(NOW)), v: 120 }])
    expect(c.series[1].pick(nh)).toEqual([{ t: Date.parse(T(NOW)), v: 300 }])
  })

  test('mqtt_backlog memakai nilai max', () => {
    const c = chartOf(systemEvidence(HEAD('mqtt_backlog', { threshold: 100, unit: '' }), t, NOW), 'mqtt_backlog')
    expect(c.series[0].pick(node({ series: { ...node().series, mqtt_backlog: [{ t: T(NOW), max: 250, avg: 10 }] } })))
      .toEqual([{ t: Date.parse(T(NOW)), v: 250 }])
  })

  test('gpu_temp dan gpu_vram memakai indeks GPU dari target', () => {
    const gpus = { '1': { util_pct: [], vram_pct: [{ t: T(NOW), max: 88 }], temp_c: [{ t: T(NOW), max: 84 }] } }
    const nh = node({ series: { ...node().series, gpus } })
    const temp = chartOf(systemEvidence(HEAD('gpu_temp', { target: 'gpu:1:1', unit: '°C', threshold: 80 }), t, NOW), 'gpu_temp')
    expect(temp.series[0].pick(nh)).toEqual([{ t: Date.parse(T(NOW)), v: 84 }])
    const vram = chartOf(systemEvidence(HEAD('gpu_vram', { target: 'gpu:1:1' }), t, NOW), 'gpu_vram')
    expect(vram.series[0].pick(nh)).toEqual([{ t: Date.parse(T(NOW)), v: 88 }])
  })

  test('camera_no_frames memakai umur frame maksimum kamera target', () => {
    const c = chartOf(systemEvidence(HEAD('camera_no_frames', { target: 'cam:3', unit: 's' }), t, NOW), 'camera_no_frames')
    const nh = node({ cameras: [{ id: 3, name: 'Lorong', target_fps: 5, fps: [], frame_age_s: [{ t: T(NOW), max: 42 }] }] })
    expect(c.series[0].pick(nh)).toEqual([{ t: Date.parse(T(NOW)), v: 42 }])
  })

  test('camera_low_fps menggambar persen terhadap target FPS', () => {
    const c = chartOf(systemEvidence(HEAD('camera_low_fps', { target: 'cam:3', unit: '%' }), t, NOW), 'camera_low_fps')
    const nh = node({ cameras: [{ id: 3, name: 'Lorong', target_fps: 8, fps: [{ t: T(NOW), min: 2 }], frame_age_s: [] }] })
    expect(c.series[0].pick(nh)).toEqual([{ t: Date.parse(T(NOW)), v: 25 }])
  })

  test('camera_low_fps: target FPS kosong atau 0 → titik dibuang', () => {
    const c = chartOf(systemEvidence(HEAD('camera_low_fps', { target: 'cam:3', unit: '%' }), t, NOW), 'camera_low_fps')
    const fps = [{ t: T(NOW), min: 2 }]
    expect(c.series[0].pick(node({ cameras: [{ id: 3, name: 'x', target_fps: null, fps, frame_age_s: [] }] }))).toEqual([])
    expect(c.series[0].pick(node({ cameras: [{ id: 3, name: 'x', target_fps: 0, fps, frame_age_s: [] }] }))).toEqual([])
    expect(c.series[0].pick(node({ cameras: [] }))).toEqual([])
  })

  test('event node offline/online: grafik CPU dan FPS inferensi, tanpa garis ambang', () => {
    const e = systemEvidence(ev(NOW - 10 * MIN, { node: 'edge-1', reason: 'timeout' }, { node_id: 1 }), t, NOW)
    expect(e.charts.map((c) => c.key)).toEqual(['node_cpu_offline', 'node_fps_offline'])
    expect(e.charts.every((c) => c.refLine === undefined)).toBe(true)
    const nh = node({ series: { ...node().series, cpu_pct: [point(5, 12)], infer_fps: [point(5, 30)] } })
    expect(e.charts[0].series[0].pick(nh)).toEqual([{ t: NOW - 5 * MIN, v: 12 }])
    expect(e.charts[1].series[0].pick(nh)).toEqual([{ t: NOW - 5 * MIN, v: 30 }])
  })

  test('tanpa node_id tidak ada grafik yang bisa diambil', () => {
    const e = systemEvidence(ev(NOW - 10 * MIN, { kind: 'health', rule: 'node_cpu', state: 'firing' }), t, NOW)
    expect(e.nodeId).toBeNull()
    expect(e.charts).toEqual([])
  })

  test('rule tak dikenal → fakta saja tanpa grafik', () => {
    const e = systemEvidence(HEAD('weird_rule'), t, NOW)
    expect(e.kind).toBe('health')
    expect(e.charts).toEqual([])
    expect(e.facts.length).toBeGreaterThan(0)
  })
})

// --- API -------------------------------------------------------------------

describe('getMonitoringHistoryWindow', () => {
  test('mengirim from/to/node_id dan mengembalikan body', async () => {
    const body = { range: 'custom', bucket_s: 60, from: T(NOW - HOUR), to: T(NOW), nodes: [] }
    const fetchMock = vi.fn(async (_url: string) => ({ ok: true, status: 200, json: () => Promise.resolve(body) }))
    vi.stubGlobal('fetch', fetchMock)
    const res = await getMonitoringHistoryWindow({ from: new Date(NOW - HOUR), to: new Date(NOW), nodeId: 4 })
    const url = String(fetchMock.mock.calls[0][0])
    expect(url).toContain('/monitoring/history?')
    expect(url).toContain(`from=${encodeURIComponent(T(NOW - HOUR))}`)
    expect(url).toContain(`to=${encodeURIComponent(T(NOW))}`)
    expect(url).toContain('node_id=4')
    expect(res).toEqual(body)
    vi.unstubAllGlobals()
  })

  test('nodeId opsional dan respons gagal melempar Error', async () => {
    const fetchMock = vi.fn(async (_url: string) => ({ ok: false, status: 500, json: () => Promise.resolve(null) }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(getMonitoringHistoryWindow({ from: new Date(NOW - HOUR), to: new Date(NOW) })).rejects.toThrow('500')
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('node_id=')
    vi.unstubAllGlobals()
  })
})

// --- perbaikan review: jendela terbalik dan rule tak dikenal ---------------

describe('systemEvidence (perbaikan review)', () => {
  test('event bertimestamp masa depan (jam node salah): jendela dianggap kosong, bukan terbalik', () => {
    const e = systemEvidence(ev(NOW + 2 * HOUR, { kind: 'health', rule: 'node_cpu', state: 'firing' }, { node_id: 1 }), t, NOW)
    expect(e.expired).toBe(false)
    expect(e.window).toBeNull()
    expect(e.facts.length).toBeGreaterThan(0)
  })

  test('rule tak dikenal: fakta Aturan memakai nama rule, bukan kunci i18n mentah', () => {
    const e = systemEvidence(ev(NOW - MIN, { kind: 'health', rule: 'future_rule', label: 'X' }, { node_id: 1 }), t, NOW)
    expect(e.facts.find((f) => f.labelKey === 'events.evidence.rule')?.value).toBe('future_rule')
    expect(e.charts).toEqual([])
  })
})
