import { apiFetch } from './client'

export type AttendanceStatus = 'ontime' | 'late' | 'waiting' | 'no_exit' | 'absent'

export type AttendanceRow = {
  id: number
  employee_id: number
  employee_code: string | null
  name: string | null
  date: string
  first_entry: string
  last_exit: string
  duration_min: number | null
  status: AttendanceStatus
  late_minutes: number | null
  override_note: string | null
  shift_name: string | null
}

export type AttendanceParams = { date?: string; from?: string; to?: string; employee_id?: number }

export type AttendancePatchBody = {
  first_entry?: string | null
  last_exit?: string | null
  status?: AttendanceStatus
  override_note: string
}

async function expectOk(res: Response, what: string) {
  if (!res.ok) throw new Error(`${what} failed: ${res.status}`)
  return res.json()
}

export async function attendanceList(params: AttendanceParams = {}): Promise<AttendanceRow[]> {
  const qs = new URLSearchParams()
  if (params.date) qs.set('date', params.date)
  if (params.from) qs.set('from', params.from)
  if (params.to) qs.set('to', params.to)
  if (params.employee_id != null) qs.set('employee_id', String(params.employee_id))
  return expectOk(await apiFetch(`/attendance${qs.toString() ? `?${qs}` : ''}`), 'list attendance')
}

export function attendanceExportUrl(from: string, to: string): string {
  return `/api/v1/attendance/rekap.csv?from=${from}&to=${to}`
}

export async function attendanceImport(file: File): Promise<{ updated: number; created: number; skipped: number }> {
  const fd = new FormData()
  fd.append('file', file)
  return expectOk(await apiFetch('/attendance/import', { method: 'POST', body: fd }), 'import attendance')
}

export async function attendancePatch(dayId: number, body: AttendancePatchBody): Promise<AttendanceRow> {
  return expectOk(await apiFetch(`/attendance/${dayId}`, { method: 'PATCH', body: JSON.stringify(body) }), 'patch attendance')
}
