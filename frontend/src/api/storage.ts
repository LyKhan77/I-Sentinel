import { apiFetch } from './client'

export type SweepResult = {
  files_deleted: number
  bytes_freed: number
  events_marked: number
  orphans_deleted: number
  events_deleted?: number // event yang medianya habis → card Events ikut dihapus
  dry_run: boolean
  clip_days?: number
  snapshot_days?: number
  attendance_days?: number
}

export type StorageSettings = {
  clip_days: number
  snapshot_days: number
  attendance_days: number // snapshot + crop wajah absensi
  disk_alert_percent: number
}

export type StorageStats = {
  retention_days: number
  // opsional: bundle lama / API lama tetap harus bisa dirender tanpa settings (tile jatuh ke retention_days)
  settings?: StorageSettings
  disk_alert?: { threshold: number; over: boolean }
  storage_root: string
  disk: { total: number; used: number; free: number; percent: number }
  kinds: Record<string, { files: number; bytes: number }>
  last_sweep: (SweepResult & { at: string }) | null
}

export async function getStorageStats(): Promise<StorageStats> {
  const res = await apiFetch('/storage/stats')
  if (!res.ok) throw new Error(`storage stats failed: ${res.status}`)
  return res.json()
}

export async function runSweep(dryRun: boolean): Promise<SweepResult> {
  const res = await apiFetch(`/storage/sweep?dry_run=${dryRun}`, { method: 'POST' })
  if (!res.ok) throw new Error(`sweep failed: ${res.status}`)
  return res.json()
}

export async function saveStorageSettings(s: StorageSettings): Promise<StorageSettings> {
  const res = await apiFetch('/storage/settings', { method: 'PUT', body: JSON.stringify(s) })
  if (res.status === 422) throw new Error('invalid')
  if (!res.ok) throw new Error(`save failed: ${res.status}`)
  return res.json()
}

// events = hapus event behavior + media; attendance_media = hanya foto/crop absensi (rekap & riwayat
// tetap); attendance_data = hapus permanen riwayat + rekap + Inbox + media absensi karyawan terpilih
export type CleanupMode = 'events' | 'attendance_media' | 'attendance_data'
export type CleanupFilter = {
  date_from: string
  date_to: string
  camera_ids: number[]
  types: string[]
  employee_ids: number[] // hanya berlaku untuk mode attendance_data
  all_employees: boolean // hanya berlaku untuk mode attendance_data
  mode: CleanupMode
}
export type CleanupEmployeeBreakdown = { id: number; name: string; attendance_events: number; days: number }
export type CleanupResult = {
  events: number
  files: number
  bytes: number
  dry_run: boolean
  attendance_events?: number
  days?: number
  employees?: CleanupEmployeeBreakdown[]
}

export async function cleanupEvents(f: CleanupFilter, dryRun: boolean): Promise<CleanupResult> {
  const res = await apiFetch('/storage/cleanup', { method: 'POST', body: JSON.stringify({ ...f, dry_run: dryRun }) })
  if (res.status === 422) throw new Error('invalid')
  if (!res.ok) throw new Error(`cleanup failed: ${res.status}`)
  return res.json()
}
