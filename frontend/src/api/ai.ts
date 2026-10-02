import { apiFetch } from './client'

export type AiStatus = {
  enabled: boolean
  presets: Record<string, string[]>
  caption_prompts: Record<string, string>
}

export async function getAiStatus(): Promise<AiStatus> {
  const res = await apiFetch('/ai/status')
  if (!res.ok) throw new Error(`AI status failed: ${res.status}`)
  return res.json()
}

export type AiRow = {
  id: number
  kind: 'caption' | 'ask'
  preset: string | null
  question: string | null
  answer: string | null
  status: 'pending' | 'ok' | 'failed'
  error: string | null
  model: string | null
  channel: string
  actor: string | null
  created_at: string
}
export type AiTurn = { q: string; a: string }
export type EventAi = { caption: AiRow | null; history: AiRow[] }
export type AskReply = { answer: string; frames_used: number; cached: boolean; latency_ms: number; model: string }

export class AiError extends Error {
  status: number
  code: string
  constructor(status: number, code: string) {
    super(code)
    this.status = status
    this.code = code
  }
}

export async function getEventAi(id: number): Promise<EventAi> {
  const res = await apiFetch(`/events/${id}/ai`)
  if (!res.ok) throw new AiError(res.status, 'generic')
  return res.json()
}

export async function askEvent(id: number, body: { question?: string; preset?: string; history?: AiTurn[] }): Promise<AskReply> {
  const res = await apiFetch(`/events/${id}/ask`, { method: 'POST', body: JSON.stringify(body) })
  if (!res.ok) {
    const error = await res.json().catch(() => null)
    throw new AiError(res.status, typeof error?.detail === 'string' ? error.detail : 'generic')
  }
  return res.json()
}
