import { useEffect, useState, type ComponentType } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Header,
  HeaderMenuButton,
  HeaderName,
  HeaderGlobalBar,
  HeaderGlobalAction,
  SideNav,
  SideNavItems,
  SideNavLink,
  SkipToContent,
} from '@carbon/react'
import {
  Dashboard,
  Video,
  EventsAlt,
  UserAvatar,
  ScanAlt,
  Settings,
  Logout,
} from '@carbon/icons-react'
import { useT, type TKey } from './i18n'
import { getMe, logout, type Me } from '../api/client'

const COLLAPSE_KEY = 'isentinel_sidenav_collapsed'
const DESKTOP_QUERY = '(min-width: 1056px)' // breakpoint lg Carbon

type Item = { to: string; key: TKey; icon: ComponentType<{ size?: number }>; adminOnly?: boolean }

const GROUPS: { key: TKey; items: Item[] }[] = [
  {
    key: 'nav.group.monitoring',
    items: [
      { to: '/dashboard', key: 'nav.dashboard', icon: Dashboard },
      { to: '/live', key: 'nav.live', icon: Video },
      { to: '/events', key: 'nav.events', icon: EventsAlt },
    ],
  },
  {
    key: 'nav.group.management',
    items: [
      { to: '/attendance', key: 'nav.attendance', icon: UserAvatar },
      { to: '/enrollment', key: 'nav.enrollment', icon: ScanAlt },
    ],
  },
  {
    key: 'nav.group.system',
    items: [{ to: '/configuration?tab=cameras', key: 'nav.configuration', icon: Settings, adminOnly: true }],
  },
]

function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(() => window.matchMedia(DESKTOP_QUERY).matches)
  useEffect(() => {
    const mq = window.matchMedia(DESKTOP_QUERY)
    const onChange = () => setIsDesktop(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return isDesktop
}

function initials(name: string) {
  return name.trim().slice(0, 2).toUpperCase()
}

export default function AppShell() {
  const { t, locale, setLocale } = useT()
  const navigate = useNavigate()
  const location = useLocation()
  const isDesktop = useIsDesktop()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === '1')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [me, setMe] = useState<Me | null>(null)

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null)) // ponytail: jsdom fetch → rejected promise; ganti router-guard data saat Fase berikutnya
  }, [location.pathname])

  // navigasi di mobile → tutup overlay
  useEffect(() => setMobileOpen(false), [location.pathname])

  const expanded = isDesktop ? !collapsed : mobileOpen
  const rail = isDesktop && collapsed

  const toggleNav = () => {
    if (isDesktop) {
      setCollapsed((c) => {
        localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1')
        return !c
      })
    } else {
      setMobileOpen((o) => !o)
    }
  }

  return (
    <>
      <Header aria-label="I-Sentinel">
        <SkipToContent />
        <HeaderMenuButton
          aria-label={rail ? t('nav.expand') : t('nav.collapse')}
          isCollapsible
          onClick={toggleNav}
          isActive={expanded}
        />
        <HeaderName href="/" prefix="">
          <span className="app-logo-mark" aria-hidden="true">
            IS
          </span>
          <span className="app-logo-word">I-Sentinel</span>
        </HeaderName>
        <span className="app-env">{t('app.env')}</span>
        <HeaderGlobalBar>
          <div className="app-lang" role="group" aria-label={t('app.lang')}>
            {(['id', 'en'] as const).map((l) => (
              <button
                key={l}
                type="button"
                className="app-lang__opt"
                aria-pressed={locale === l}
                onClick={() => setLocale(l)}
              >
                {l.toUpperCase()}
              </button>
            ))}
          </div>
          <HeaderGlobalAction
            aria-label={t('login.logout')}
            tooltipAlignment="end"
            onClick={async () => {
              await logout()
              navigate('/login')
            }}
          >
            <Logout size={20} />
          </HeaderGlobalAction>
        </HeaderGlobalBar>
      </Header>

      <SideNav
        aria-label="I-Sentinel"
        isChildOfHeader
        expanded={expanded}
        isRail={rail}
        addMouseListeners={false}
      >
        <SideNavItems>
          {GROUPS.map((g) => {
            const items = g.items.filter((i) => !i.adminOnly || me?.role === 'admin')
            if (items.length === 0) return null
            return (
              <li key={g.key}>
                <div className="app-sidenav-group">{t(g.key)}</div>
                <ul className="app-sidenav-items">
                  {items.map((i) => (
                    <SideNavLink
                      key={i.to}
                      as={NavLink}
                      to={i.to}
                      isActive={location.pathname === i.to.split('?')[0]}
                      renderIcon={i.icon}
                    >
                      {t(i.key)}
                    </SideNavLink>
                  ))}
                </ul>
              </li>
            )
          })}
          {me && (
            <li className="app-sidenav-user">
              <span className="app-sidenav-user__avatar" aria-hidden="true">
                {initials(me.username)}
              </span>
              <span className="app-sidenav-user__info">
                <span className="app-sidenav-user__name">{me.username}</span>
                <br />
                <span className="app-sidenav-user__role">
                  {me.role === 'admin' ? t('app.role.admin') : t('app.role.viewer')}
                </span>
              </span>
            </li>
          )}
        </SideNavItems>
      </SideNav>

      <main
        id="main-content"
        className={rail ? 'app-main app-main--rail' : 'app-main'}
      >
        <Outlet context={me} />
      </main>
    </>
  )
}
