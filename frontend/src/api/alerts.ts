import { apiFetch } from './client'

export type AlertStatus = 'sent' | 'failed' | 'rate_limited' | 'not_configured' | 'queued'

export type AlertOut = {
  id: number
  event_id: number
  camera_id: number | null
  zone_id: number | null
  type: string
  severity: string
  status: AlertStatus
  error: string | null
  chat_id: string | null
  created_at: string
}

export type TelegramStatus = { configured: boolean; active_chats: number }

export async function listAlerts(eventId?: number): Promise<AlertOut[]> {
  const qs = new URLSearchParams()
  if (eventId != null) qs.set('event_id', String(eventId))
  const res = await apiFetch(`/alerts${qs.toString() ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error(`list alerts failed: ${res.status}`)
  return res.json()
}

// Event.event_id (uuid) → latest alert status; one request for the whole list badge
export async function alertsByEvents(ids: string[]): Promise<Record<string, AlertStatus>> {
  if (ids.length === 0) return {}
  const res = await apiFetch(`/alerts/by-events?ids=${encodeURIComponent(ids.join(','))}`)
  if (!res.ok) throw new Error(`alerts by events failed: ${res.status}`)
  return res.json()
}

export async function telegramStatus(): Promise<TelegramStatus> {
  const res = await apiFetch('/telegram/status')
  if (!res.ok) throw new Error(`telegram status failed: ${res.status}`)
  return res.json()
}
