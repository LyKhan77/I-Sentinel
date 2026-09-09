import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, Outlet, RouterProvider, useLocation } from 'react-router-dom'
import '@carbon/react/index.scss'
import './app/theme.scss'
import AppShell from './app/AppShell'
import LoginPage from './features/auth/LoginPage'
import { I18nProvider, useT } from './app/i18n'
import { getMe } from './api/client'
import type { Me } from './api/client'

// ponytail: segmen pertama path → label nav; route placeholder nyata ditambah saat fiturnya ada
const SEGMENT_TO_KEY: Record<string, 'nav.dashboard' | 'nav.live' | 'nav.events' | 'nav.attendance' | 'nav.enrollment' | 'nav.configuration'> = {
  dashboard: 'nav.dashboard',
  live: 'nav.live',
  events: 'nav.events',
  attendance: 'nav.attendance',
  enrollment: 'nav.enrollment',
  configuration: 'nav.configuration',
}

function Placeholder() {
  const { t } = useT()
  const segment = useLocation().pathname.split('/').filter(Boolean)[0]
  const titleKey = (segment && SEGMENT_TO_KEY[segment]) || 'nav.dashboard'
  return <h1 style={{ padding: 32, fontWeight: 300 }}>{t(titleKey)}</h1>
}

function RequireAuth() {
  const [me, setMe] = useState<Me | null | 'loading'>('loading')

  useEffect(() => {
    let live = true
    getMe().then((m) => {
      if (!live) return
      if (m) setMe(m)
      else window.location.assign('/login')
    })
    return () => {
      live = false
    }
  }, [])

  if (me === 'loading') return null
  return <Outlet />
}

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        path: '/',
        element: <AppShell />,
        children: [
          { index: true, element: <Navigate to="/dashboard" replace /> },
          { path: 'dashboard', element: <Placeholder /> },
          { path: '*', element: <Placeholder /> },
        ],
      },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider>
      <RouterProvider router={router} />
    </I18nProvider>
  </StrictMode>,
)
