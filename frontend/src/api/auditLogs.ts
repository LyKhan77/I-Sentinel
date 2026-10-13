import { apiFetch } from './client'

export type AuditLogEntry = {
  id: number
  ts: string
  category: string
  action: string
  actor_id: number | null
  actor_label: string
  target_type: string | null
  target_id: string | null
  target_label: string | null
  changes: Record<string, unknown> | null
  ip: string | null
  user_agent: string | null
  status: string
}

export type AuditLogPage = { total: number; items: AuditLogEntry[] }
export type AuditVerifyResult = { ok: boolean; checked: number; first_break_id: number | null }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `http ${res.status}`)
  }
  return res.json()
}

export type AuditQuery = {
  from?: string
  to?: string
  category?: string
  action?: string
  actor?: string
  status?: string
  q?: string
  limit?: number
  offset?: number
}

export function listAuditLogs(query: AuditQuery): Promise<AuditLogPage> {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== '') params.set(k, String(v))
  }
  const qs = params.toString()
  return call<AuditLogPage>(`/audit-logs${qs ? `?${qs}` : ''}`)
}

export const listAuditActors = () => call<string[]>('/audit-logs/actors')

export const verifyAuditChain = () =>
  call<AuditVerifyResult>('/audit-logs/verify', { method: 'POST' })
