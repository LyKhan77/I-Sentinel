import { apiFetch } from './client'

export type Health = 'ok' | 'warning' | 'critical' | 'unknown' | 'disabled'
export type HostStats = { cpu_pct: number | null; ram_used_mb: number | null; ram_total_mb: number | null
  disk_used_pct: number | null; disk_free_gb: number | null }
export type MonGpu = { idx: number | null; name: string | null; util_pct: number | null; vram_used_mb: number | null
  vram_total_mb: number | null; temp_c: number | null; power_w: number | null }
export type MonNode = { id: number; name: string; status: string; last_seen: string | null; age_s: number | null
  health: Health; issues: string[]; host: HostStats; gpus: MonGpu[]
  inference: { detector: { model: string | null; device: string | null; ms_avg: number | null; ms_max: number | null
    infer_fps: number | null }; face: { loaded: boolean | null; queue: number | null }; mqtt_backlog: number | null } }
export type MonCamera = { id: number; name: string; location: string | null; node_id: number | null
  node_name: string | null; enabled: boolean; analyzed: boolean; health: Health; issues: string[]
  ai: { state: string | null; fps: number | null; target_fps: number | null; last_frame_age_s: number | null
    reconnects_1h: number; motion_skip_pct: number | null } | null
  stream: { registered: boolean | null } }
export type MonService = { key: string; health: Health; detail: string | null; latency_ms: number | null }
export type Counts = { ok: number; warning: number; critical: number; disabled?: number }
export type Monitoring = { generated_at: string
  summary: { health: Health; cameras: Counts; nodes: Counts; services: Counts }
  server: HostStats; nodes: MonNode[]; cameras: MonCamera[]; services: MonService[] }

export async function getMonitoring(): Promise<Monitoring> {
  const res = await apiFetch('/monitoring')
  if (!res.ok) throw new Error(`monitoring failed: ${res.status}`)
  return res.json()
}

export type HistoryRange = '1h' | '6h' | '24h' | '7d'
export type HistPoint = { t: string; avg?: number | null; max?: number | null; min?: number | null }
export type GpuHistory = { util_pct: HistPoint[]; vram_pct: HistPoint[]; temp_c: HistPoint[] }
export type NodeHistory = { id: number; name: string
  series: { cpu_pct: HistPoint[]; ram_pct: HistPoint[]; ms_avg: HistPoint[]; ms_max: HistPoint[]
    infer_fps: HistPoint[]; mqtt_backlog: HistPoint[]; gpus: Record<string, GpuHistory> }
  cameras: { id: number; name: string; target_fps: number | null; fps: HistPoint[]; frame_age_s: HistPoint[] }[]
  offline: { from: string; to: string | null }[] }
export type MonitoringHistory = { range: HistoryRange; bucket_s: number; from: string; to: string; nodes: NodeHistory[] }

export async function getMonitoringHistory(range: HistoryRange): Promise<MonitoringHistory> {
  const res = await apiFetch(`/monitoring/history?range=${range}`)
  if (!res.ok) throw new Error(`monitoring history failed: ${res.status}`)
  return res.json()
}
