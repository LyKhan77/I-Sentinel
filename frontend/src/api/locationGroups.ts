import { apiFetch } from './client'

export type LocationGroup = {
  id: number
  name: string
  sort_order: number
  enabled: boolean
}

export type LocationGroupPayload = {
  name: string
  sort_order?: number
  enabled?: boolean
}

async function expectOk(res: Response, what: string) {
  if (!res.ok) throw new Error(`${what} failed: ${res.status}`)
  return res.json()
}

export async function listLocationGroups(): Promise<LocationGroup[]> {
  return expectOk(await apiFetch('/location-groups'), 'list location groups')
}

export async function createLocationGroup(payload: LocationGroupPayload): Promise<LocationGroup> {
  return expectOk(await apiFetch('/location-groups', {
    method: 'POST',
    body: JSON.stringify(payload),
  }), 'create location group')
}

export async function updateLocationGroup(id: number, patch: Partial<LocationGroupPayload>): Promise<LocationGroup> {
  return expectOk(await apiFetch(`/location-groups/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  }), 'update location group')
}

export async function deleteLocationGroup(id: number): Promise<void> {
  const res = await apiFetch(`/location-groups/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`delete location group failed: ${res.status}`)
}
