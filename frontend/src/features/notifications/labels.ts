import type { EventOut } from '../../api/events'
import type { TKey } from '../../app/i18n'

export type Sev = 'critical' | 'warning' | 'info'
const SEVS: readonly string[] = ['critical', 'warning', 'info']

/** Severity tak dikenal → warning (warna tetap terlihat). */
export const sevClass = (s: string): Sev => (SEVS.includes(s) ? (s as Sev) : 'warning')

/** Label jenis event: behavior memakai label zona; system = "Node offline". */
export const typeKey = (type: string): TKey =>
  type === 'system' ? 'notif.type.system' : (`zones.behavior.${type}` as TKey)

/** Lokasi event: "Node X offline" untuk system, selain itu "kamera · zona". */
export function eventWhere(e: EventOut, t: (k: TKey) => string, cameraName: (id: number | null) => string): string {
  if (e.type === 'system') return t('notif.nodeOffline').replace('{node}', String(e.payload?.node ?? '?'))
  const zone = typeof e.payload?.zone_name === 'string' && e.payload.zone_name ? e.payload.zone_name : null
  return zone ? `${cameraName(e.camera_id)} · ${zone}` : cameraName(e.camera_id)
}
