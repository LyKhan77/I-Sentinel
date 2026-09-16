import { apiFetch } from './client'

export type ProbeStream = { res: string; fps: number; codec: string }

export type Camera = {
  id: number
  name: string
  location: string | null
  host: string
  rtsp_main: string | null
  rtsp_sub: string | null
  node_id: number | null
  enabled: boolean
  status: string
  probe_main: ProbeStream | null
  probe_sub: ProbeStream | null
}

export type CameraNode = { id: number; name: string; type: string; status: string }

export type ProbeResult = {
  main: ProbeStream | null
  sub: ProbeStream | null
  main_path: string | null
  sub_path: string | null
}

export type CameraPayload = {
  name: string
  location?: string | null
  host: string
  rtsp_main?: string | null
  rtsp_sub?: string | null
  node_id?: number | null
  probe_main?: ProbeStream | null
  probe_sub?: ProbeStream | null
  status?: string
}

export type CameraImportEntry = {
  name: string
  location: string | null
  host: string
  rtsp_main: string
  rtsp_sub: string | null
}

export type CameraImportItem = {
  camera_id: number | null
  matched: boolean
  changed: boolean
  before: CameraImportEntry | null
  after: CameraImportEntry
}

export type CameraImportResult = {
  applied: boolean
  total: number
  matched: number
  updated: number
  unmatched: CameraImportItem[]
  errors: string[]
  items: CameraImportItem[]
}

async function expectOk(res: Response, what: string) {
  if (!res.ok) throw new Error(`${what} failed: ${res.status}`)
  return res.json()
}

export async function listCameras(): Promise<Camera[]> {
  const res = await apiFetch('/cameras')
  return expectOk(res, 'list cameras')
}

export async function createCamera(payload: CameraPayload): Promise<Camera> {
  const res = await apiFetch('/cameras', { method: 'POST', body: JSON.stringify(payload) })
  if (res.status === 409) throw new Error('duplicate')
  return expectOk(res, 'create camera')
}

export async function updateCamera(id: number, patch: Partial<CameraPayload> & { enabled?: boolean }): Promise<Camera> {
  const res = await apiFetch(`/cameras/${id}`, { method: 'PATCH', body: JSON.stringify(patch) })
  return expectOk(res, 'update camera')
}

export async function importCameras(entries: CameraImportEntry[], apply = false): Promise<CameraImportResult> {
  const res = await apiFetch(`/cameras/import${apply ? '?apply=true' : ''}`, {
    method: 'POST',
    body: JSON.stringify({ entries }),
  })
  return expectOk(res, 'import cameras')
}

export async function deleteCamera(id: number): Promise<void> {
  const res = await apiFetch(`/cameras/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`delete camera failed: ${res.status}`)
}

export async function probeCamera(host: string, cameraId?: number): Promise<ProbeResult> {
  const res = await apiFetch('/cameras/probe', {
    method: 'POST',
    body: JSON.stringify(cameraId != null ? { host, camera_id: cameraId } : { host }),
  })
  return expectOk(res, 'probe')
}

export async function listNodes(): Promise<CameraNode[]> {
  const res = await apiFetch('/nodes')
  return expectOk(res, 'list nodes')
}
