import { apiFetch } from './client'

export type ZoneType = 'restricted' | 'absensi' | 'free'

export type Schedule = { days: number[]; start: string; end: string }

export type Zone = {
  id: number
  camera_id: number
  name: string
  type: ZoneType
  direction: 'entry' | 'exit' | null
  polygon: [number, number][]
  schedule: Schedule | null
  severity: 'critical' | 'warning'
  rate_limit_min: number
  snapshot: boolean
  telegram: boolean
  active: boolean
  camera_name?: string | null
}

export type ZonePayload = {
  name?: string
  type?: ZoneType
  direction?: 'entry' | 'exit' | null
  polygon?: [number, number][]
  schedule?: Schedule | null
  severity?: 'critical' | 'warning'
  snapshot?: boolean
  telegram?: boolean
  active?: boolean
}

async function expectOk(res: Response, what: string) {
  if (!res.ok) throw new Error(`${what} failed: ${res.status}`)
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
