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
