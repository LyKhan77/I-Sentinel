import { renderHook, waitFor, act, cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { summarizeCameras, summarizeAttendance } from '../features/dashboard/summary'
import { useDashboardData, DASH_POLL_MS, type Source } from '../features/dashboard/useDashboardData'
import { mon, alert, stats, att, storage, ok, fail } from './dashboardFixtures'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

type Bodies = Record<Source, (() => unknown) | null>
const defaultBodies = (): Bodies => ({
  monitoring: () => mon(),
  alerts: () => ({ active: [alert()], recent: [] }),
  stats: () => stats(),
  attendance: () => [att('ontime'), att('late')],
  storage: () => storage(),
})

function stubFetch(bodies: Bodies = defaultBodies()) {
  const calls: Record<Source, number> = { monitoring: 0, alerts: 0, stats: 0, attendance: 0, storage: 0 }
  const fetchMock = vi.fn(async (url: string) => {
    const u = String(url)
    const key: Source | null = u.endsWith('/monitoring/alerts') ? 'alerts' : u.endsWith('/monitoring') ? 'monitoring'
      : u.endsWith('/events/stats/today') ? 'stats' : u.endsWith('/attendance') ? 'attendance'
      : u.endsWith('/storage/stats') ? 'storage' : null
    if (!key) return fail()
    calls[key]++
    const body = bodies[key]
    return body === null ? fail() : ok(body())
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, bodies }
}

describe('summarizeCameras', () => {
  test('counts healthy, total and problems from summary.cameras', () => {
    expect(summarizeCameras(mon())).toEqual({ healthy: 1, total: 3, problems: 2 })
  })
  test('zero cameras is a successful 0, not missing data', () => {
    expect(summarizeCameras(mon({ summary: { cameras: { ok: 0, warning: 0, critical: 0 } } })))
      .toEqual({ healthy: 0, total: 0, problems: 0 })
  })
})

describe('summarizeAttendance', () => {
  test('present excludes absent; late and needsFix counted', () => {
    const rows = [att('ontime'), att('late'), att('no_exit'), att('no_entry'), att('absent'), att('waiting')]
    expect(summarizeAttendance(rows)).toEqual({ present: 5, late: 1, needsFix: 2 })
  })
  test('empty list → all zero', () => {
    expect(summarizeAttendance([])).toEqual({ present: 0, late: 0, needsFix: 0 })
  })
})

describe('useDashboardData', () => {
  test('loads all five sources and ends loading', async () => {
    stubFetch()
    const { result } = renderHook(() => useDashboardData())
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.monitoring).not.toBeNull()
    expect(result.current.alerts).toHaveLength(1)
    expect(result.current.stats?.total).toBe(47)
    expect(result.current.attendance).toHaveLength(2)
    expect(result.current.storage).not.toBeNull()
    expect(Object.values(result.current.failed).every((f) => f === false)).toBe(true)
    expect(result.current.updatedAt).not.toBeNull()
  })

  test('a failed source leaves only its own value null', async () => {
    stubFetch({ ...defaultBodies(), stats: null })
    const { result } = renderHook(() => useDashboardData())
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.stats).toBeNull()
    expect(result.current.failed.stats).toBe(true)
    expect(result.current.monitoring).not.toBeNull()
    expect(result.current.failed.monitoring).toBe(false)
  })

  test('keeps the last good value when a later poll fails', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const { bodies } = stubFetch()
    const { result } = renderHook(() => useDashboardData())
    await waitFor(() => expect(result.current.stats).not.toBeNull())
    const first = result.current.stats
    bodies.stats = null
    await act(async () => {
      vi.advanceTimersByTime(DASH_POLL_MS)
    })
    await waitFor(() => expect(result.current.failed.stats).toBe(true))
    expect(result.current.stats).toBe(first)
  })

  test('refetches stats only when statsKey changes, not on mount', async () => {
    const { calls } = stubFetch()
    const { result, rerender } = renderHook(
      ({ key }: { key: number | null }) => useDashboardData(key),
      { initialProps: { key: null } as { key: number | null } },
    )
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(calls.stats).toBe(1)
    expect(calls.monitoring).toBe(1)
    rerender({ key: 42 })
    await waitFor(() => expect(calls.stats).toBe(2))
    expect(calls.monitoring).toBe(1)
  })
})
