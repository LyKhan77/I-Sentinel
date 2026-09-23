import { apiFetch } from './client'

export type DetectorSettings = { default_ai_fps: number; default_confidence: number; motion_enabled: boolean; motion_threshold: number; motion_min_area: number; motion_force_interval_s: number; face_min_width_px: number; face_min_det_score: number; face_max_yaw: number; face_blur_min: number; face_min_frames: number; updated_at: string }

async function json(res: Response) { if (!res.ok) throw new Error(`detector settings failed: ${res.status}`); return res.json() }
export async function getDetectorSettings(): Promise<DetectorSettings> { return json(await apiFetch('/detector-settings')) }
export async function putDetectorSettings(values: Omit<DetectorSettings, 'updated_at'>): Promise<DetectorSettings> { return json(await apiFetch('/detector-settings', { method: 'PUT', body: JSON.stringify(values) })) }
