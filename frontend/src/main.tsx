import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, Outlet, RouterProvider } from 'react-router-dom'
import '@carbon/react/index.scss'
import './app/theme.scss'
import AppShell from './app/AppShell'
import LoginPage from './features/auth/LoginPage'
import { I18nProvider, useT } from './app/i18n'
import { getMe } from './api/client'
import type { Me } from './api/client'

function Placeholder({ titleKey }: { titleKey: 'nav.dashboard' }) {
  const { t } = useT()
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
          { path: 'dashboard', element: <Placeholder titleKey="nav.dashboard" /> },
          { path: '*', element: <Placeholder titleKey="nav.dashboard" /> },
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
