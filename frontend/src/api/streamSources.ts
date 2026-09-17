import { apiFetch } from './client'

export type SourceKind = 'nvr' | 'ip_camera' | 'unknown'

export type StreamSource = {
  id: number
  name: string
  kind: SourceKind
  host: string
  port: number
  vendor: string | null
  default_credential_id: number | null
  enabled: boolean
}

export type StreamSourcePayload = {
  name: string
  kind: SourceKind
  host: string
  port?: number
  vendor?: string | null
  default_credential_id?: number | null
  enabled?: boolean
}

async function expectOk(res: Response, what: string) {
  if (!res.ok) throw new Error(`${what} failed: ${res.status}`)
  return res.json()
}

export async function listStreamSources(): Promise<StreamSource[]> {
  return expectOk(await apiFetch('/stream-sources'), 'list stream sources')
}

export async function createStreamSource(payload: StreamSourcePayload): Promise<StreamSource> {
  return expectOk(await apiFetch('/stream-sources', {
    method: 'POST',
    body: JSON.stringify(payload),
  }), 'create stream source')
}

export async function updateStreamSource(id: number, patch: Partial<StreamSourcePayload>): Promise<StreamSource> {
  return expectOk(await apiFetch(`/stream-sources/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  }), 'update stream source')
}

export async function deleteStreamSource(id: number): Promise<void> {
  const res = await apiFetch(`/stream-sources/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`delete stream source failed: ${res.status}`)
}

