import { useEffect, useRef, useState } from 'react'
import { getMonitoring, getHealthAlerts, type HealthAlert, type Monitoring } from '../../api/monitoring'
import { eventStats, type EventStats } from '../../api/events'
import { attendanceList, type AttendanceRow } from '../../api/attendance'
import { getStorageStats, type StorageStats } from '../../api/storage'

export const DASH_POLL_MS = 15_000

export type Source = 'monitoring' | 'alerts' | 'stats' | 'attendance' | 'storage'

export type DashboardData = {
  monitoring: Monitoring | null
  alerts: HealthAlert[] | null
  stats: EventStats | null
  attendance: AttendanceRow[] | null
  storage: StorageStats | null
  loading: boolean
  updatedAt: Date | null
  failed: Record<Source, boolean>
}

const NO_FAILURES: Record<Source, boolean> = {
  monitoring: false, alerts: false, stats: false, attendance: false, storage: false,
}

/**
 * Data Dashboard: lima sumber read-only, polling 15 detik, kegagalan terisolasi
 * per sumber — nilai sukses terakhir bertahan saat poll berikutnya gagal (§3.2).
 * `statsKey` (id event realtime terakhir) me-refetch stats saja di antara poll.
 */
export function useDashboardData(statsKey?: number | null): DashboardData {
  const [monitoring, setMonitoring] = useState<Monitoring | null>(null)
  const [alerts, setAlerts] = useState<HealthAlert[] | null>(null)
  const [stats, setStats] = useState<EventStats | null>(null)
  const [attendance, setAttendance] = useState<AttendanceRow[] | null>(null)
  const [storage, setStorage] = useState<StorageStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [failed, setFailed] = useState<Record<Source, boolean>>(NO_FAILURES)

  useEffect(() => {
    let alive = true
    const grab = <T>(source: Source, p: Promise<T>, set: (v: T) => void) =>
      p.then(
        (v) => {
          if (!alive) return
          set(v)
          setFailed((f) => ({ ...f, [source]: false }))
          setUpdatedAt(new Date())
        },
        () => {
          if (alive) setFailed((f) => ({ ...f, [source]: true }))
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
  }, [])

  const statsKeyRef = useRef(statsKey)
  useEffect(() => {
    if (statsKeyRef.current === statsKey) return // lewati eksekusi pertama (siklus mount sudah memuat stats)
    statsKeyRef.current = statsKey
    let alive = true
    eventStats().then(
      (v) => {
        if (!alive) return
        setStats(v)
        setFailed((f) => ({ ...f, stats: false }))
        setUpdatedAt(new Date())
      },
      () => {
        if (alive) setFailed((f) => ({ ...f, stats: true }))
      },
    )
    return () => {
      alive = false
    }
  }, [statsKey])

  return { monitoring, alerts, stats, attendance, storage, loading, updatedAt, failed }
}
