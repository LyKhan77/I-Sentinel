import type { EventOut } from '../../api/events'
import { EVENT_TYPES } from './eventTypes'

// Filter Events hidup di URL (D1): fungsi murni parse/write tanpa sisi-efek, supaya
// EventsPage tinggal menurunkan nilai dari `useSearchParams` dan menulis lewat setter.
// Nilai tak valid jatuh ke default; param bernilai default tidak ditulis ke URL.

export const RANGE_IDS = ['all', 'today', '24h', '7d', '30d'] as const
export type RangeId = (typeof RANGE_IDS)[number]
export const SECURITY = 'security'
export type Filters = { type: string | null; camera: number | null; severity: string | null; range: RangeId; q: string }

const SEVERITIES = ['critical', 'warning', 'info']
const RANGE_HOURS: Partial<Record<RangeId, number>> = { '24h': 24, '7d': 24 * 7, '30d': 24 * 30 }
const DEFAULTS: Filters = { type: null, camera: null, severity: null, range: 'all', q: '' }
const Q_MAX = 100

/** Baca filter dari query string; nilai tak valid → default (tanpa error). */
export function parseFilters(params: URLSearchParams): Filters {
  const rawType = params.get('type')
  const rawCam = params.get('camera')
  const rawSev = params.get('severity')
  const rawRange = params.get('range')
  const cam = rawCam != null && /^\d+$/.test(rawCam) && Number(rawCam) > 0 ? Number(rawCam) : null
  return {
    type: rawType === SECURITY || (EVENT_TYPES as readonly string[]).includes(rawType ?? '') ? rawType : null,
    camera: cam,
    severity: SEVERITIES.includes(rawSev ?? '') ? rawSev : null,
    range: (RANGE_IDS as readonly string[]).includes(rawRange ?? '') ? (rawRange as RangeId) : 'all',
    q: (params.get('q') ?? '').slice(0, Q_MAX),
  }
}

/** Tulis patch filter ke query string baru: param lain (mis. `event`) terjaga, default dihapus. */
export function writeFilters(prev: URLSearchParams, patch: Partial<Filters>): URLSearchParams {
  const next = new URLSearchParams(prev)
  for (const key of ['type', 'camera', 'severity', 'range', 'q'] as const) {
    if (!(key in patch)) continue
    const v = patch[key] ?? DEFAULTS[key]
    if (v === DEFAULTS[key] || v === '' || v == null) next.delete(key)
    else next.set(key, String(v))
  }
  return next
}

/** Daftar tipe untuk server: grup `security` = semua kecuali absensi (D3). */
export function typesFor(type: string | null): string[] | undefined {
  if (type == null) return undefined
  if (type === SECURITY) return EVENT_TYPES.filter((t) => t !== 'attendance')
  return [type]
}

/** Batas bawah waktu untuk server: `today` = 00:00 lokal (D2). */
export function sinceFor(range: RangeId, now: Date): string | undefined {
  if (range === 'all') return undefined
  if (range === 'today') return new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString()
  const h = RANGE_HOURS[range]
  return h ? new Date(now.getTime() - h * 3_600_000).toISOString() : undefined
}

/** Cocok untuk event live/daftar klien: tipe (termasuk grup), kamera, severity — bukan range/q. */
export function matchesFilters(e: EventOut, f: Filters): boolean {
  if (f.type === SECURITY ? e.type === 'attendance' : f.type != null && e.type !== f.type) return false
  if (f.camera != null && e.camera_id !== f.camera) return false
  if (f.severity != null && e.severity !== f.severity) return false
  return true
}

/** Halaman berikutnya digabung di akhir: buang id yang sudah ada, potong ke cap. */
export function appendPage(prev: EventOut[], rows: EventOut[], cap: number): EventOut[] {
  const seen = new Set(prev.map((e) => e.id))
  return [...prev, ...rows.filter((e) => !seen.has(e.id))].slice(0, cap)
}

/** Halaman pertama digabung di depan (urutan server); baris lama yang tak ada dipertahankan urut. */
export function mergeFirstPage(prev: EventOut[], rows: EventOut[], cap: number): EventOut[] {
  const fresh = new Set(rows.map((e) => e.id))
  return [...rows, ...prev.filter((e) => !fresh.has(e.id))].slice(0, cap)
}
