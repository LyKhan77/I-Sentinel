import type { TKey } from '../../app/i18n'

// Daftar tipe = `ALLOWED_TYPES` ingest backend. Statis (bukan turunan data) supaya
// opsi tidak muncul/hilang saat event berubah dan labelnya selalu terlokalisasi.
export const EVENT_TYPES = ['intrusion', 'loitering', 'running', 'idle_zone', 'crowd', 'attendance', 'person_detect', 'system'] as const

/** Tipe perilaku alert: isi grup "Keamanan" dan satu-satunya kind ber-delivery (Plan B). */
export const BEHAVIOR_TYPES = ['intrusion', 'loitering', 'running', 'idle_zone', 'crowd'] as const

const EVENT_TYPE_KEYS: Record<string, TKey> = {
  attendance: 'events.type.attendance',
  person_detect: 'events.type.person_detect',
  system: 'events.type.system',
}

/** Label tipe event: behavior memakai label zona, system/attendance/person_detect khusus, sisanya teks mentah. */
export function eventTypeLabel(type: string, t: (k: TKey) => string): string {
  if ((BEHAVIOR_TYPES as readonly string[]).includes(type)) return t(`zones.behavior.${type}` as TKey)
  const key = EVENT_TYPE_KEYS[type]
  return key ? t(key) : type
}
