import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, HeaderGlobalAction, Tab, TabList, TabPanel, TabPanels, Tabs, Toggle } from '@carbon/react'
import { Notification as NotificationIcon } from '@carbon/icons-react'
import type { EventOut } from '../../api/events'
import { useT } from '../../app/i18n'
import { useEventAlerts } from './EventAlertsProvider'
import { dayStart, eventWhere, sevClass, typeKey } from './labels'

const BADGE_MAX = 99

/** Lonceng header: badge belum dibaca + panel tab Hari ini / Kemarin. Membuka panel = semua dibaca. */
export default function NotificationBell() {
  const { t, locale } = useT()
  const navigate = useNavigate()
  const { recent, unread, markAllRead, muted, setMuted, cameraName } = useEventAlerts()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onDown = (e: MouseEvent) => {
      const root = rootRef.current
      // klik di luar panel menutup; target bisa bukan Element (mis. document) → jangan menyentuh contains
      if (root && e.target instanceof Node && !root.contains(e.target)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  const toggle = () => {
    if (!open) markAllRead()
    setOpen((o) => !o)
  }
  const go = (to: string) => {
    setOpen(false)
    navigate(to)
  }
  // batas hari dihitung saat render (panel dibuka) → tetap benar setelah lewat tengah malam
  const todayFrom = dayStart(0).getTime()
  const yesterdayFrom = dayStart(1).getTime()
  const ts = (e: EventOut) => Date.parse(e.ts_event)
  const days = [
    { key: 'today', label: t('notif.today'), items: recent.filter((e) => ts(e) >= todayFrom) },
    { key: 'yesterday', label: t('notif.yesterday'),
      items: recent.filter((e) => ts(e) >= yesterdayFrom && ts(e) < todayFrom) },
  ]
  const label = unread > 0 ? t('notif.bellUnread').replace('{n}', String(unread)) : t('notif.bell')

  return (
    <div className="nb" ref={rootRef}>
      <HeaderGlobalAction aria-label={label} isActive={open} onClick={toggle} data-testid="notif-bell">
        <NotificationIcon size={20} />
        {unread > 0 && (
          <span className="nb__badge" data-testid="notif-badge" aria-hidden="true">
            {unread > BADGE_MAX ? `${BADGE_MAX}+` : unread}
          </span>
        )}
      </HeaderGlobalAction>
      {open && (
        <div className="nb__panel" role="dialog" aria-label={t('notif.title')} data-testid="notif-panel">
          <div className="nb__head">
            <strong>{t('notif.title')}</strong>
            <Toggle id="notif-sound" data-testid="notif-sound" size="sm" labelText={t('notif.sound')}
              toggled={!muted} onToggle={(on) => setMuted(!on)} />
          </div>
          <Tabs>
            <TabList aria-label={t('notif.title')} className="nb__tabs">
              {days.map((d) => (
                <Tab key={d.key} data-testid={`notif-tab-${d.key}`}>{`${d.label} (${d.items.length})`}</Tab>
              ))}
            </TabList>
            <TabPanels>
              {days.map((d) => (
                <TabPanel key={d.key} className="nb__tabpanel">
                  {d.items.length === 0 ? (
                    <p className="nb__empty">{t('notif.empty')}</p>
                  ) : (
                    <ul className="nb__list">
                      {d.items.map((e) => (
                        <li key={e.id}>
                          <button type="button" className="nb__item" data-testid={`notif-item-${e.id}`}
                            onClick={() => go(`/events?event=${e.id}`)}>
                            <span className={`ev-dot ev-dot--${sevClass(e.severity)}`} aria-hidden="true" />
                            <span className="nb__text">
                              <span>{t(typeKey(e.type))}</span>
                              <span className="nb__sub">{eventWhere(e, t, cameraName)}</span>
                              <span className="nb__sub">
                                {new Date(e.ts_event).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}
                              </span>
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </TabPanel>
              ))}
            </TabPanels>
          </Tabs>
          <div className="nb__foot">
            <Button kind="ghost" size="sm" onClick={() => go('/events')}>{t('notif.viewAll')}</Button>
          </div>
        </div>
      )}
    </div>
  )
}
