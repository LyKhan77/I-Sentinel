// Fixture bersama untuk uji Dashboard (Task 2) — bentuknya mengikuti respons API nyata.
import type { Monitoring, MonNode, HealthAlert } from '../api/monitoring'
import type { EventOut, EventStats } from '../api/events'
import type { AttendanceRow, AttendanceStatus } from '../api/attendance'
import type { StorageStats } from '../api/storage'
import type { DashboardData } from '../features/dashboard/useDashboardData'

const nowIso = () => new Date().toISOString()

export function monNode(over: Partial<MonNode> = {}): MonNode {
  return {
    id: 1, name: 'server', status: 'online', last_seen: nowIso(), age_s: 2, health: 'ok', issues: [],
    host: { cpu_pct: 12, ram_used_mb: 8000, ram_total_mb: 32000, disk_used_pct: 62, disk_free_gb: 120 },
    gpus: [{ idx: 0, name: 'NVIDIA GeForce RTX 4090', util_pct: 55, vram_used_mb: 5000, vram_total_mb: 24000, temp_c: 61, power_w: 220 }],
    inference: {
      detector: { model: 'yolo26s.engine', device: 'cuda:0', ms_avg: 9, ms_max: 20, infer_fps: 24 },
      face: { loaded: true, queue: 0 }, mqtt_backlog: 0,
    },
    ...over,
  }
}

type MonOverride = Omit<Partial<Monitoring>, 'summary'> & { summary?: Partial<Monitoring['summary']> }

export function mon(over: MonOverride = {}): Monitoring {
  const base: Monitoring = {
    generated_at: nowIso(),
    summary: { health: 'ok', cameras: { ok: 1, warning: 1, critical: 1 }, nodes: { ok: 1, warning: 0, critical: 0 }, services: { ok: 3, warning: 0, critical: 0 } },
    server: { cpu_pct: 10, ram_used_mb: 8000, ram_total_mb: 32000, disk_used_pct: 50, disk_free_gb: 200 },
    nodes: [monNode()],
    cameras: [],
    services: [],
  }
  return { ...base, ...over, summary: { ...base.summary, ...(over.summary ?? {}) } }
}

export function alert(over: Partial<HealthAlert> = {}): HealthAlert {
  return {
    id: 1, rule: 'camera_no_frames', target: 'camera:1', label: 'CAM-01', node_id: 1, camera_id: 1,
    severity: 'warning', value: 30, threshold: 10, unit: 'mnt', started_at: nowIso(), resolved_at: null,
    ...over,
  }
}

export function ev(id: number, over: Partial<EventOut> = {}): EventOut {
  return {
    id, event_id: `ev-${id}`, type: 'intrusion', camera_id: 1, zone_id: null, severity: 'critical',
    ts_event: nowIso(), payload: null, clip_path: null, snapshot_path: 'snapshots/x.jpg',
    ...over,
  }
}

export function stats(over: Partial<EventStats> = {}): EventStats {
  return {
    total: 47, by_type: { intrusion: 12, loitering: 8 }, by_severity: { critical: 3, warning: 20, info: 24 },
    by_hour: Array(24).fill(0), critical_by_hour: Array(24).fill(0),
    ...over,
  }
}

let attId = 1
export function att(status: AttendanceStatus, over: Partial<AttendanceRow> = {}): AttendanceRow {
  return {
    id: attId++, employee_id: 1, employee_code: 'E-01', name: 'Budi', date: '2026-09-30',
    first_entry: '07:55', last_exit: '', duration_min: null, status, late_minutes: null,
    override_note: null, shift_name: 'Pagi',
    ...over,
  }
}

const GB = 1024 ** 3

export function storage(over: Partial<StorageStats> = {}): StorageStats {
  return {
    retention_days: 30, storage_root: '/data/isentinel',
    // backend mengirim byte (shutil.disk_usage): 62% dari 100 GB
    disk: { total: 100 * GB, used: 62 * GB, free: 38 * GB, percent: 62 }, kinds: {}, last_sweep: null,
    ...over,
  }
}

// Respons fetch palsu; nilai `null` di router bodies → `fail()` (500, bukan 401:
// apiFetch melempar window.location.assign saat 401).
export const ok = (body: unknown) => ({ ok: true, status: 200, json: () => Promise.resolve(body) })
export const fail = () => ({ ok: false, status: 500, json: () => Promise.resolve(null) })

export function emptyData(over: Partial<DashboardData> = {}): DashboardData {
  return {
    monitoring: null, alerts: null, stats: null, attendance: null, storage: null,
    loading: false, updatedAt: null,
    lastOk: { monitoring: null, alerts: null, stats: null, attendance: null, storage: null },
    failed: { monitoring: false, alerts: false, stats: false, attendance: false, storage: false },
    ...over,
  }
}
