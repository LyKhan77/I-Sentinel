import { apiFetch } from './client'

export type AiSettings = {
  enabled: boolean
  api_url: string
  model: string
  max_tokens: number
  timeout_caption_s: number
  timeout_ask_s: number
  ask_rate_per_min: number
  caption_min_interval_s: number
  extra_body: Record<string, unknown>
  key_configured: boolean
  key_source: 'db' | 'env' | 'none'
  sources: Record<string, 'db' | 'env' | 'default'>
  restart_only: { concurrency: number; queue_max: number }
}
export type AiSettingsPatch = {
  [K in keyof Omit<AiSettings, 'key_configured' | 'key_source' | 'sources' | 'restart_only'>]?: AiSettings[K] | null
} & { api_key?: string; clear_api_key?: boolean }
export type AiTestResult = {
  ok: boolean; vision_ok: boolean; latency_ms: number | null; model: string | null; error: string | null
}

/** `detail` is the backend validation message (field names only, never submitted values); null otherwise. */
export class AiSettingsError extends Error {
  status: number
  detail: string | null
  constructor(status: number, detail: string | null) {
    super(`AI settings failed: ${status}`)
    this.status = status
    this.detail = detail
  }
}

async function ok<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new AiSettingsError(response.status, typeof body?.detail === 'string' ? body.detail : null)
  }
  return response.json()
}

export async function getAiSettings(): Promise<AiSettings> {
  return ok(await apiFetch('/ai/settings'))
}

export async function putAiSettings(patch: AiSettingsPatch): Promise<AiSettings> {
  return ok(await apiFetch('/ai/settings', { method: 'PUT', body: JSON.stringify(patch) }))
}

export async function testAiSettings(patch: AiSettingsPatch): Promise<AiTestResult> {
  return ok(await apiFetch('/ai/settings/test', { method: 'POST', body: JSON.stringify(patch) }))
}
