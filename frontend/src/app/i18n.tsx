import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

const STORAGE_KEY = 'isentinel_locale'

const dicts = {
  id: {
    'nav.dashboard': 'Dashboard',
    'nav.live': 'Live View',
    'nav.events': 'Events',
    'nav.attendance': 'Attendance',
    'nav.enrollment': 'Enrollment',
    'nav.configuration': 'Konfigurasi',
    'nav.group.monitoring': 'Monitoring',
    'nav.group.management': 'Management',
    'nav.group.system': 'System',
    'app.env': 'Fase 0',
    'login.title': 'Masuk ke I-Sentinel',
    'login.username': 'Nama pengguna',
    'login.password': 'Kata sandi',
    'login.submit': 'Masuk',
    'login.required': 'wajib diisi',
    'login.invalid': 'Nama pengguna atau kata sandi salah',
    'login.logout': 'Keluar',
    'common.loading': 'Memuat…',
    'common.error': 'Terjadi kesalahan',
    'common.cancel': 'Batal',
    'common.save': 'Simpan',
    'cameras.title': 'Kamera',
    'cameras.add': '+ Tambah kamera',
    'cameras.col.name': 'Nama',
    'cameras.col.streams': 'Stream',
    'cameras.col.node': 'Node',
    'cameras.col.status': 'Status',
    'cameras.status.online': 'Online',
    'cameras.status.offline': 'Offline',
    'cameras.status.unknown': 'Tidak diketahui',
    'cameras.streamFail': 'gagal',
    'cameras.probe': 'Probe',
    'cameras.disable': 'Nonaktifkan',
    'cameras.enable': 'Aktifkan',
    'cameras.delete': 'Hapus',
    'cameras.empty': 'Belum ada kamera terdaftar',
    'cameras.loadError': 'Gagal memuat daftar kamera',
    'cameras.probeError': 'Probe gagal',
    'cameras.saveError': 'Gagal menyimpan perubahan',
    'cameras.deleteConfirmTitle': 'Hapus kamera',
    'cameras.deleteConfirmBody': 'Hapus kamera "{name}"? Tindakan ini tidak dapat dibatalkan.',
    'cameras.wizard.title': 'Tambah kamera',
    'cameras.wizard.name': 'Nama kamera',
    'cameras.wizard.location': 'Lokasi',
    'cameras.wizard.host': 'IP / Host',
    'cameras.wizard.node': 'Node',
    'cameras.wizard.probe': 'Probe stream',
    'cameras.wizard.probing': 'Memprobe stream…',
    'cameras.wizard.probeHint': 'Isi form, lalu klik "Probe stream".',
    'cameras.wizard.probeFail': 'gagal · timeout',
    'cameras.wizard.duplicate': 'Kamera dengan host tersebut sudah terdaftar',
  },
  en: {
    'nav.dashboard': 'Dashboard',
    'nav.live': 'Live View',
    'nav.events': 'Events',
    'nav.attendance': 'Attendance',
    'nav.enrollment': 'Enrollment',
    'nav.configuration': 'Configuration',
    'nav.group.monitoring': 'Monitoring',
    'nav.group.management': 'Management',
    'nav.group.system': 'System',
    'app.env': 'Phase 0',
    'login.title': 'Sign in to I-Sentinel',
    'login.username': 'Username',
    'login.password': 'Password',
    'login.submit': 'Sign in',
    'login.required': 'is required',
    'login.invalid': 'Invalid username or password',
    'login.logout': 'Log out',
    'common.loading': 'Loading…',
    'common.error': 'Something went wrong',
    'common.cancel': 'Cancel',
    'common.save': 'Save',
    'cameras.title': 'Cameras',
    'cameras.add': '+ Add camera',
    'cameras.col.name': 'Name',
    'cameras.col.streams': 'Streams',
    'cameras.col.node': 'Node',
    'cameras.col.status': 'Status',
    'cameras.status.online': 'Online',
    'cameras.status.offline': 'Offline',
    'cameras.status.unknown': 'Unknown',
    'cameras.streamFail': 'failed',
    'cameras.probe': 'Probe',
    'cameras.disable': 'Disable',
    'cameras.enable': 'Enable',
    'cameras.delete': 'Delete',
    'cameras.empty': 'No cameras registered yet',
    'cameras.loadError': 'Failed to load cameras',
    'cameras.probeError': 'Probe failed',
    'cameras.saveError': 'Failed to save changes',
    'cameras.deleteConfirmTitle': 'Delete camera',
    'cameras.deleteConfirmBody': 'Delete camera "{name}"? This cannot be undone.',
    'cameras.wizard.title': 'Add camera',
    'cameras.wizard.name': 'Camera name',
    'cameras.wizard.location': 'Location',
    'cameras.wizard.host': 'IP / Host',
    'cameras.wizard.node': 'Node',
    'cameras.wizard.probe': 'Probe stream',
    'cameras.wizard.probing': 'Probing streams…',
    'cameras.wizard.probeHint': 'Fill the form, then click "Probe stream".',
    'cameras.wizard.probeFail': 'failed · timeout',
    'cameras.wizard.duplicate': 'A camera with this host is already registered',
  },
} as const

export type Locale = keyof typeof dicts
export type TKey = keyof (typeof dicts)['id']

type I18nCtx = { locale: Locale; setLocale: (l: Locale) => void; t: (key: TKey) => string }

const Ctx = createContext<I18nCtx | null>(null)

function initialLocale(): Locale {
  return localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'id'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale)
  const setLocale = useCallback((l: Locale) => {
    localStorage.setItem(STORAGE_KEY, l)
    setLocaleState(l)
  }, [])
  const t = useCallback((key: TKey) => dicts[locale][key] ?? key, [locale])
  return <Ctx.Provider value={{ locale, setLocale, t }}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useT() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useT must be used within I18nProvider')
  return ctx
}
