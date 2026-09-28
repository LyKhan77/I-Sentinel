import { apiFetch } from './client'

export type Role = 'admin' | 'viewer'
export type User = {
  id: number
  username: string
  role: Role
  locale: string
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

// Gagal → Error(detail server) agar UI memetakan pesan stabil backend (app/api/users.py); 422 → 'invalid'.
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(res.status === 422 ? 'invalid' : typeof body?.detail === 'string' ? body.detail : `http ${res.status}`)
  }
  return res.json()
}

export const listUsers = () => call<User[]>('/users')
export const createUser = (b: { username: string; role: Role; password: string }) =>
  call<User>('/users', { method: 'POST', body: JSON.stringify(b) })
export const updateUser = (id: number, b: { role?: Role; is_active?: boolean; password?: string }) =>
  call<User>(`/users/${id}`, { method: 'PATCH', body: JSON.stringify(b) })
export const deleteUser = (id: number) => call<{ ok: boolean }>(`/users/${id}`, { method: 'DELETE' })
