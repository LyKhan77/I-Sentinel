const BASE = '/api/v1'

export type Me = { id: number; username: string; role: 'admin' | 'viewer'; locale?: string | null }

export async function apiFetch(path: string, opts: RequestInit = {}): Promise<Response> {
  const { headers, ...rest } = opts
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    credentials: 'include',
    headers: rest.body ? { 'Content-Type': 'application/json', ...headers } : headers,
  })
  if (res.status === 401 && window.location.pathname !== '/login') {
    window.location.assign('/login')
  }
  return res
}

export async function login(username: string, password: string): Promise<Me> {
  const res = await apiFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error(res.status === 401 ? 'invalid' : `login failed: ${res.status}`)
  const data = await res.json()
  return data.user
}

export async function getMe(): Promise<Me | null> {
  const res = await apiFetch('/auth/me')
  if (res.status === 401) return null
  if (!res.ok) throw new Error(`getMe failed: ${res.status}`)
  return res.json()
}

export async function logout(): Promise<void> {
  await apiFetch('/auth/logout', { method: 'POST' })
}
