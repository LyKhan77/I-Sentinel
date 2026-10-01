import { useCallback, useEffect, useRef, useState } from 'react'
import { getMonitoring, getHealthAlerts, type HealthAlert, type Monitoring } from '../../api/monitoring'
import { eventStats, type EventStats } from '../../api/events'
import { attendanceList, type AttendanceRow } from '../../api/attendance'
import { getStorageStats, type StorageStats } from '../../api/storage'

export const DASH_POLL_MS = 15_000
// event realtime beruntun (burst) → satu refetch stats; tiap refetch = scan event hari ini di backend
export const STATS_DEBOUNCE_MS = 2_000

export type Source = 'monitoring' | 'alerts' | 'stats' | 'attendance' | 'storage'

export type DashboardData = {
  monitoring: Monitoring | null
  alerts: HealthAlert[] | null
  stats: EventStats | null
  attendance: AttendanceRow[] | null
  storage: StorageStats | null
  loading: boolean
  /** Sukses terakhir dari sumber mana pun (catatan "Diperbarui"). */
  updatedAt: Date | null
  /** Sukses terakhir per sumber; dasar catatan basi untuk sumber yang gagal. */
  lastOk: Record<Source, Date | null>
  failed: Record<Source, boolean>
}

const NO_FAILURES: Record<Source, boolean> = {
  monitoring: false, alerts: false, stats: false, attendance: false, storage: false,
}
const NO_OK: Record<Source, Date | null> = {
  monitoring: null, alerts: null, stats: null, attendance: null, storage: null,
}

/**
 * Data Dashboard: lima sumber read-only, polling 15 detik, kegagalan terisolasi
 * per sumber — nilai sukses terakhir bertahan saat poll berikutnya gagal (§3.2).
 * `statsKey` (id event realtime terakhir) me-refetch stats saja di antara poll,
 * di-debounce `STATS_DEBOUNCE_MS`.
 */
export function useDashboardData(statsKey?: number | null): DashboardData {
  const [monitoring, setMonitoring] = useState<Monitoring | null>(null)
  const [alerts, setAlerts] = useState<HealthAlert[] | null>(null)
  const [stats, setStats] = useState<EventStats | null>(null)
  const [attendance, setAttendance] = useState<AttendanceRow[] | null>(null)
  const [storage, setStorage] = useState<StorageStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [lastOk, setLastOk] = useState<Record<Source, Date | null>>(NO_OK)
  const [failed, setFailed] = useState<Record<Source, boolean>>(NO_FAILURES)

  const record = useCallback((source: Source, success: boolean) => {
    if (success) {
      const now = new Date()
      setUpdatedAt(now)
      setLastOk((l) => ({ ...l, [source]: now }))
    }
    setFailed((f) => ({ ...f, [source]: !success }))
  }, [])

  useEffect(() => {
    let alive = true
    const grab = <T>(source: Source, p: Promise<T>, set: (v: T) => void) =>
      p.then(
        (v) => {
          if (!alive) return
          set(v)
          record(source, true)
        },
        () => {
          if (alive) record(source, false)
        },
      )
    const cycle = () => Promise.all([
      grab('monitoring', getMonitoring(), setMonitoring),
      grab('alerts', getHealthAlerts().then((r) => r.active), setAlerts),
      grab('stats', eventStats(), setStats),
      grab('attendance', attendanceList(), setAttendance),
      grab('storage', getStorageStats(), setStorage),
    ]).then(() => {
      if (alive) setLoading(false)
    })
    cycle()
    const timer = setInterval(cycle, DASH_POLL_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [record])

  const statsKeyRef = useRef(statsKey)
  useEffect(() => {
    if (statsKeyRef.current === statsKey) return // lewati eksekusi pertama (siklus mount sudah memuat stats)
    statsKeyRef.current = statsKey
    let alive = true
    const timer = setTimeout(() => {
      eventStats().then(
        (v) => {
          if (!alive) return
          setStats(v)
          record('stats', true)
        },
        () => {
          if (alive) record('stats', false)
        },
      )
    }, STATS_DEBOUNCE_MS)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [statsKey, record])

  return { monitoring, alerts, stats, attendance, storage, loading, updatedAt, lastOk, failed }
}
