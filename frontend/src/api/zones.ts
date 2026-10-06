import { apiFetch } from './client'

export type ZoneType = 'attendance' | 'behavior'

export type BehaviorKind = 'intrusion' | 'loitering' | 'running' | 'idle_zone' | 'crowd'

/** Satu behavior zona; `trigger_seconds` = lama di zona sebelum event terbit (0 = langsung). */
export type Behavior = {
  kind: BehaviorKind | 'attendance'
  trigger_seconds: number
  speed_limit_mps?: number
  min_count?: number // crowd
  reminder_minutes?: number // idle/crowd; 0 disables reminders
  snapshot?: boolean // kosong = ikut flag zona (data lama)
  clip?: boolean
  telegram?: boolean // kosong = ikut flag zona / default off
}

export type Schedule = { days: number[]; start: string; end: string }
export type ZoneSchedule = Schedule | { shift_id: number }

export type Zone = {
  id: number
  camera_id: number
  name: string
  type: ZoneType
  direction: 'entry' | 'exit' | null
  polygon: [number, number][]
  schedule: ZoneSchedule | null
  severity: 'critical' | 'warning'
  rate_limit_min: number
  trigger_seconds: number
  behaviors: Behavior[]
  snapshot: boolean
  clip: boolean
  telegram: boolean
  // Optional for locally drawn zones and pre-migration data; API responses include both.
  ai_caption?: boolean
  ai_prompt?: string | null
  active: boolean
  camera_name?: string | null
}

export type ZonePayload = {
  name?: string
  type?: ZoneType
  direction?: 'entry' | 'exit' | null
  polygon?: [number, number][]
  schedule?: ZoneSchedule | null
  severity?: 'critical' | 'warning'
  trigger_seconds?: number
  behaviors?: Behavior[]
  snapshot?: boolean
  clip?: boolean
  telegram?: boolean
  ai_caption?: boolean
  ai_prompt?: string | null
  active?: boolean
}

async function expectOk(res: Response, what: string) {
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body && typeof body.detail === 'string' ? `: ${body.detail}` : ''
    throw new Error(`${what} failed: ${res.status}${detail}`)
  }
  return res.json()
}

export async function listZones(cameraId?: number): Promise<Zone[]> {
  const qs = cameraId != null ? `?camera_id=${cameraId}` : ''
  return expectOk(await apiFetch(`/zones${qs}`), 'list zones')
}

export async function createZone(cameraId: number, payload: ZonePayload): Promise<Zone> {
  return expectOk(
    await apiFetch('/zones', { method: 'POST', body: JSON.stringify({ camera_id: cameraId, ...payload }) }),
    'create zone',
  )
}

export async function updateZone(id: number, patch: ZonePayload): Promise<Zone> {
  return expectOk(await apiFetch(`/zones/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }), 'update zone')
}

export async function deleteZone(id: number): Promise<void> {
  if (!(await apiFetch(`/zones/${id}`, { method: 'DELETE' })).ok) throw new Error('delete zone failed')
}
