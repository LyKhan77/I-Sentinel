import type { AttendanceRow } from '../../api/attendance'
import type { Monitoring } from '../../api/monitoring'

/** Ringkasan kamera untuk tile Dashboard: sehat = health ok; total mengecualikan `disabled`. */
export function summarizeCameras(m: Monitoring): { healthy: number; total: number; problems: number } {
  const { ok, warning, critical } = m.summary.cameras
  return { healthy: ok, total: ok + warning + critical, problems: warning + critical }
}

/** hadir = status ≠ absent; perlu koreksi = no_exit + no_entry (K3, tanpa penyebut). */
export function summarizeAttendance(rows: AttendanceRow[]): { present: number; late: number; needsFix: number } {
  let present = 0
  let late = 0
  let needsFix = 0
  for (const r of rows) {
    if (r.status !== 'absent') present++
    if (r.status === 'late') late++
    if (r.status === 'no_exit' || r.status === 'no_entry') needsFix++
  }
  return { present, late, needsFix }
}
