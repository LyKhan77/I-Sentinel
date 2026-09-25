import { apiFetch } from './client'

export type CredentialProfile = {
  id: number
  name: string
  username: string
  secret_ref: string
  enabled: boolean
}

export type CredentialProfilePayload = {
  name: string
  username?: string
  secret_ref?: string // env:NAMA (lama)
  password?: string   // write-only → file rahasia server
  enabled?: boolean
}

async function expectOk(res: Response, what: string) {
  if (!res.ok) throw new Error(`${what} failed: ${res.status}`)
  return res.json()
}

export async function listCredentialProfiles(): Promise<CredentialProfile[]> {
  return expectOk(await apiFetch('/credential-profiles'), 'list credential profiles')
}

export async function createCredentialProfile(payload: CredentialProfilePayload): Promise<CredentialProfile> {
  return expectOk(await apiFetch('/credential-profiles', {
    method: 'POST',
    body: JSON.stringify(payload),
  }), 'create credential profile')
}

export async function updateCredentialProfile(id: number, patch: Partial<CredentialProfilePayload>): Promise<CredentialProfile> {
  return expectOk(await apiFetch(`/credential-profiles/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  }), 'update credential profile')
}
