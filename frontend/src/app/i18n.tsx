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
