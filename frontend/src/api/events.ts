import { apiFetch } from './client'

export type EventOut = {
  id: number
  event_id: string
  type: string
  camera_id: number
  zone_id: number | null
  severity: string
  ts_event: string
  payload: Record<string, unknown> | null
  clip_path: string | null
  snapshot_path: string | null
}

export type EventStats = { total: number; by_type: Record<string, number> }

export type EventListParams = { camera_id?: number; type?: string; since?: string; limit?: number }

export async function listEvents(params: EventListParams = {}): Promise<EventOut[]> {
  const qs = new URLSearchParams()
  if (params.camera_id != null) qs.set('camera_id', String(params.camera_id))
  if (params.type) qs.set('type', params.type)
  if (params.since) qs.set('since', params.since)
  if (params.limit != null) qs.set('limit', String(params.limit))
  const res = await apiFetch(`/events${qs.toString() ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error(`list events failed: ${res.status}`)
  return res.json()
}

export async function eventStats(): Promise<EventStats> {
  const res = await apiFetch('/events/stats/today')
  if (!res.ok) throw new Error(`event stats failed: ${res.status}`)
  return res.json()
}

// endpoint /live per kamera: snapshot URL + stream info (go2rtc); WebRTC nyata menyusul Task 9
export type LiveInfo = {
  camera_id: number
  streams: { sub?: string; main?: string }
  webrtc?: string
  mse?: string
  hls?: string
  snapshot?: string
}

export async function getLive(cameraId: number): Promise<LiveInfo> {
  const res = await apiFetch(`/cameras/${cameraId}/live`)
  if (!res.ok) throw new Error(`live info failed: ${res.status}`)
  return res.json()
}
