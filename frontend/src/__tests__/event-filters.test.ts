import { expect, test } from 'vitest'
import {
  parseFilters,
  writeFilters,
  typesFor,
  sinceFor,
  matchesFilters,
  appendPage,
  mergeFirstPage,
  SECURITY,
  type Filters,
} from '../features/events/eventFilters'
import type { EventOut } from '../api/events'

function ev(over: Partial<EventOut> = {}): EventOut {
  return {
    id: 1, event_id: 'e-1', type: 'intrusion', camera_id: 1, zone_id: null, severity: 'critical',
    ts_event: '2026-10-01T10:00:00Z', payload: null, clip_path: null, snapshot_path: null, ...over,
  }
}

const F = (over: Partial<Filters> = {}): Filters => ({
  type: null, camera: null, severity: null, range: 'all', q: '', ...over,
})

test('parseFilters defaults for empty params', () => {
  expect(parseFilters(new URLSearchParams())).toEqual(F())
})

test('parseFilters reads valid values', () => {
  const f = parseFilters(new URLSearchParams('type=system&camera=2&severity=critical&range=today&q=gate'))
  expect(f).toEqual({ type: 'system', camera: 2, severity: 'critical', range: 'today', q: 'gate' })
})

test('parseFilters falls back to defaults for invalid values', () => {
  for (const qs of ['type=foo', 'camera=abc', 'camera=0', 'camera=-1', 'camera=1.5', 'severity=x', 'range=99d']) {
    expect(parseFilters(new URLSearchParams(qs))).toEqual(F())
  }
})

test('parseFilters keeps the security group and truncates q to 100', () => {
  expect(parseFilters(new URLSearchParams(`type=${SECURITY}`)).type).toBe(SECURITY)
  const long = 'x'.repeat(150)
  expect(parseFilters(new URLSearchParams(`q=${long}`)).q).toHaveLength(100)
})

test('writeFilters drops default values, keeps other params and does not mutate prev', () => {
  const prev = new URLSearchParams('event=5&type=system')
  const next = writeFilters(prev, { type: null, camera: 3, severity: null, range: 'all', q: '' })
  expect(next.get('event')).toBe('5')
  expect(next.has('type')).toBe(false)
  expect(next.get('camera')).toBe('3')
  expect(next.has('severity')).toBe(false)
  expect(next.has('range')).toBe(false)
  expect(next.has('q')).toBe(false)
  // prev utuh (setter bentuk fungsi memanggil ini dengan params aktif)
  expect(prev.get('type')).toBe('system')
  expect([...prev.keys()]).toEqual(['event', 'type'])
})

test('writeFilters writes non-default values', () => {
  const next = writeFilters(new URLSearchParams(), { type: SECURITY, range: 'today', q: 'gate' })
  expect(next.get('type')).toBe(SECURITY)
  expect(next.get('range')).toBe('today')
  expect(next.get('q')).toBe('gate')
})

test('typesFor security excludes attendance and keeps the other seven', () => {
  const types = typesFor(SECURITY)
  expect(types).toHaveLength(7)
  expect(types).not.toContain('attendance')
  expect(types).toContain('system')
  expect(types).toContain('intrusion')
})

test('typesFor single type wraps it, null means no filter', () => {
  expect(typesFor('system')).toEqual(['system'])
  expect(typesFor(null)).toBeUndefined()
})

test('sinceFor today is local midnight of that day', () => {
  const now = new Date('2026-10-01T15:30:00') // waktu lokal, tanpa Z
  expect(sinceFor('today', now)).toBe(new Date(2026, 9, 1).toISOString())
})

test('sinceFor finite ranges subtracts the window from now, all is undefined', () => {
  const now = new Date('2026-10-01T15:30:00')
  expect(sinceFor('24h', now)).toBe(new Date(now.getTime() - 24 * 3_600_000).toISOString())
  expect(sinceFor('all', now)).toBeUndefined()
})

test('matchesFilters security group rejects attendance and accepts system', () => {
  const f = F({ type: SECURITY })
  expect(matchesFilters(ev({ type: 'attendance' }), f)).toBe(false)
  expect(matchesFilters(ev({ type: 'system' }), f)).toBe(true)
})

test('matchesFilters checks camera and severity too', () => {
  expect(matchesFilters(ev(), F({ camera: 2 }))).toBe(false)
  expect(matchesFilters(ev(), F({ severity: 'warning' }))).toBe(false)
  expect(matchesFilters(ev(), F({ type: 'intrusion', camera: 1, severity: 'critical' }))).toBe(true)
})

test('appendPage appends at the end, drops duplicate ids and truncates to cap', () => {
  const prev = [ev({ id: 1 }), ev({ id: 2 })]
  const rows = [ev({ id: 2 }), ev({ id: 3 }), ev({ id: 4 })]
  expect(appendPage(prev, rows, 10).map((e) => e.id)).toEqual([1, 2, 3, 4])
  expect(appendPage(prev, rows, 3).map((e) => e.id)).toEqual([1, 2, 3])
})

test('mergeFirstPage puts fresh rows first, keeps the rest in order and truncates to cap', () => {
  const prev = [ev({ id: 1 }), ev({ id: 2 }), ev({ id: 3 })]
  const rows = [ev({ id: 4 }), ev({ id: 2, severity: 'info' })] // id 2 versi baru
  const merged = mergeFirstPage(prev, rows, 10)
  expect(merged.map((e) => e.id)).toEqual([4, 2, 1, 3])
  expect(merged.find((e) => e.id === 2)?.severity).toBe('info') // isi baris ikut yang baru
  expect(mergeFirstPage(prev, rows, 2).map((e) => e.id)).toEqual([4, 2])
})
