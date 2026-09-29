import { apiFetch } from './client'

export type SweepResult = {
  files_deleted: number
  bytes_freed: number
  events_marked: number
  orphans_deleted: number
  dry_run: boolean
  clip_days?: number
  snapshot_days?: number
}

export type StorageSettings = { clip_days: number; snapshot_days: number; disk_alert_percent: number }

export type StorageStats = {
  retention_days: number
  settings: StorageSettings
  disk_alert: { threshold: number; over: boolean }
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
