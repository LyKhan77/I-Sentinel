import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Header,
  HeaderContainer,
  HeaderName,
  HeaderMenuButton,
  HeaderSideNavItems,
  HeaderGlobalBar,
  HeaderGlobalAction,
  SideNav,
  SideNavItems,
  SideNavMenuItem,
  SideNavDivider,
  SkipToContent,
  Tag,
  Button,
} from '@carbon/react'
import {
  Dashboard,
  Video,
  EventsAlt,
  UserAvatar,
  ScanAlt,
  Settings,
  ChevronDown,
} from '@carbon/icons-react'
import { useT, type TKey } from './i18n'
import { getMe, logout, type Me } from '../api/client'

const COLLAPSE_KEY = 'isentinel_sidenav_collapsed'

// ponytail: satu grup render saja — System grup mockup masih kosong, tambah item saat ada fitur
type Item = { to: string; key: TKey; icon: React.ReactNode; adminOnly?: boolean }

const GROUPS: { key: TKey; items: Item[] }[] = [
  {
    key: 'nav.group.monitoring',
    items: [
      { to: '/dashboard', key: 'nav.dashboard', icon: <Dashboard size={16} /> },
      { to: '/live', key: 'nav.live', icon: <Video size={16} /> },
      { to: '/events', key: 'nav.events', icon: <EventsAlt size={16} /> },
    ],
  },
  {
    key: 'nav.group.management',
    items: [
      { to: '/attendance', key: 'nav.attendance', icon: <UserAvatar size={16} /> },
      { to: '/enrollment', key: 'nav.enrollment', icon: <ScanAlt size={16} /> },
      { to: '/configuration', key: 'nav.configuration', icon: <Settings size={16} />, adminOnly: true },
    ],
  },
]

export default function AppShell() {
  const { t, locale, setLocale } = useT()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === '1')
  const [me, setMe] = useState<Me | null>(null)
  const location = useLocation()

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null)) // ponytail: jsdom fetch → rejected promise; ganti router-guard data saat Fase berikutnya
  }, [location.pathname])

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1')
      return !c
    })
  }

  return (
    <HeaderContainer
      render={({ isSideNavExpanded, onClickSideNavExpand }) => (
        <>
          <Header aria-label="I-Sentinel">
            <SkipToContent />
            <HeaderMenuButton
              aria-label="Toggle menu"
              isCollapsible
              onClick={onClickSideNavExpand}
              isActive={isSideNavExpanded}
            />
            <HeaderName href="#" prefix="">
              IS
            </HeaderName>
            <Tag type="blue" size="sm" title={t('app.env')}>
              {t('app.env')}
            </Tag>
            <HeaderGlobalBar>
              <Button
                kind="ghost"
                size="sm"
                onClick={() => setLocale(locale === 'id' ? 'en' : 'id')}
              >
                {locale === 'id' ? 'ID' : 'EN'}
              </Button>
              <HeaderGlobalAction
                aria-label={t('login.logout')}
                onClick={async () => {
                  await logout()
                  navigate('/login')
                }}
              >
                <ChevronDown size={20} />
              </HeaderGlobalAction>
            </HeaderGlobalBar>
          </Header>
          <SideNav aria-label="I-Sentinel" expanded={!collapsed} onToggle={toggleCollapsed} isChildOfHeader>
            <SideNavItems>
              {GROUPS.map((g) => {
                const items = g.items.filter((i) => !i.adminOnly || me?.role === 'admin')
                if (items.length === 0) return null
                return (
                  <div key={g.key}>
                    <h3 className="cds--side-nav__submenu" style={{ padding: '6px 16px', color: 'var(--cds-text-secondary)', fontSize: 12, margin: 0 }}>
                      {t(g.key)}
                    </h3>
                    {items.map((i) => (
                      <SideNavMenuItem key={i.to} renderIcon={() => i.icon} isActive={location.pathname === i.to}>
                        <NavLink to={i.to} style={{ color: 'inherit', textDecoration: 'none', display: 'block' }}>
                          {t(i.key)}
                        </NavLink>
                      </SideNavMenuItem>
                    ))}
                    <SideNavDivider />
                  </div>
                )
              })}
              {me && (
                <div style={{ padding: '12px 16px', fontSize: 13 }}>
                  <div>{me.username}</div>
                  <div style={{ color: 'var(--cds-text-secondary)' }}>{me.role}</div>
                </div>
              )}
              <HeaderSideNavItems>
                {/* isi menu header (mobile) — kosong di Fase 0 */}
              </HeaderSideNavItems>
            </SideNavItems>
          </SideNav>
          <main id="main-content" style={{ paddingTop: '48px', minHeight: '100vh' }}>
            <Outlet context={me} />
          </main>
        </>
      )}
    />
  )
}
