import { apiFetch } from './client'

export type TelegramSettings = {
  has_token: boolean
  chat_id: string | null
  chat_title: string | null
  app_url: string | null
  last_alert: { status: string; error: string | null; created_at: string } | null
}
export type TelegramChat = { chat_id: string; title: string; type: string }
export type TelegramSettingsPatch = { token?: string; chat_id?: string; chat_title?: string; app_url?: string | null }

async function ok<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) throw new Error(`${what} failed: ${res.status}`)
  return res.json()
}

export async function getTelegramSettings(): Promise<TelegramSettings> {
  return ok(await apiFetch('/telegram/settings'), 'telegram settings')
}

export async function putTelegramSettings(patch: TelegramSettingsPatch): Promise<TelegramSettings> {
  return ok(await apiFetch('/telegram/settings', { method: 'PUT', body: JSON.stringify(patch) }), 'save telegram settings')
}

export async function discoverTelegramChats(): Promise<TelegramChat[]> {
  return (await ok<{ chats: TelegramChat[] }>(await apiFetch('/telegram/discover', { method: 'POST' }), 'discover')).chats
}

export async function sendTelegramTest(): Promise<{ status: string; error: string | null }> {
  return ok(await apiFetch('/telegram/test', { method: 'POST' }), 'telegram test')
}
