// Mode TV (kiosk) untuk command center: tanpa AppShell, grid memenuhi layar, toolbar auto-hide,
// pengaturan per layar (?screen=A / ?screen=B untuk dua monitor di satu Pi).
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Toggle } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import CameraPicker from './CameraPicker'
import LiveWall from './LiveWall'
import { useLiveCameras } from './useLiveCameras'
import { useAutoScroll, useIdle } from './useAutoScroll'
import { COL_OPTIONS, SCROLL_SPEEDS, screenName, selectCameras, useScreenPrefs, type ScrollSpeed } from './screenPrefs'
import { useEventAlerts } from '../notifications/EventAlertsProvider'
import NodeOfflineBanner from '../../components/NodeOfflineBanner'

export const TOOLBAR_HIDE_MS = 4000
export const SCROLL_RESUME_MS = 10000
const SPEEDS = Object.keys(SCROLL_SPEEDS) as ScrollSpeed[]

export default function LiveTvPage() {
  const { t } = useT()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const screen = screenName(params.get('screen'))
  const [prefs, update] = useScreenPrefs(screen)
  const { cams, lives, loading, loadFailed } = useLiveCameras()
  const [pickerOpen, setPickerOpen] = useState(false)
  const [debugOpen, setDebugOpen] = useState(false)
  const barHidden = useIdle(TOOLBAR_HIDE_MS)
  const resumed = useIdle(SCROLL_RESUME_MS)
  const { muted, setMuted } = useEventAlerts()

  useAutoScroll({
    on: prefs.scroll.on,
    pxPerSec: SCROLL_SPEEDS[prefs.scroll.speed],
    paused: !resumed || pickerOpen || debugOpen,
  })

  const active = cams.filter((c) => c.enabled)
  const shown = selectCameras(active, prefs.cameras)
  const showBar = !barHidden || pickerOpen

  const exit = () => {
    if (document.fullscreenElement) void document.exitFullscreen?.().catch(() => {})
    navigate('/live')
  }

  return (
    <div data-testid="live-tv" className={showBar ? 'lv-tv' : 'lv-tv lv-tv--idle'}>
      {showBar && (
        <div className="lv-tv__bar" data-testid="live-tv-toolbar">
          <strong>{t('live.tv.screen').replace('{name}', screen)}</strong>
          {COL_OPTIONS.map((n) => (
            <button key={n} type="button" data-testid={`live-tv-cols-${n}`} aria-pressed={prefs.cols === n}
              className={prefs.cols === n ? 'lv-chip lv-chip--sel' : 'lv-chip'} onClick={() => update({ cols: n })}>
              {t('live.cols').replace('{n}', String(n))}
            </button>
          ))}
          <CameraPicker cams={active} value={prefs.cameras} onChange={(cameras) => update({ cameras })}
            open={pickerOpen} onOpenChange={setPickerOpen} />
          <Toggle id="live-tv-scroll" data-testid="live-tv-scroll" size="sm" labelText={t('live.tv.autoScroll')}
            hideLabel toggled={prefs.scroll.on} onToggle={(on) => update({ scroll: { ...prefs.scroll, on } })} />
          <span>{t('live.tv.autoScroll')}</span>
          {SPEEDS.map((s) => (
            <button key={s} type="button" data-testid={`live-tv-speed-${s}`} aria-pressed={prefs.scroll.speed === s}
              className={prefs.scroll.speed === s ? 'lv-chip lv-chip--sel' : 'lv-chip'}
              onClick={() => update({ scroll: { ...prefs.scroll, speed: s } })}>
              {t(`live.tv.speed.${s}` as TKey)}
            </button>
          ))}
          <Toggle id="live-tv-sound" data-testid="live-tv-sound" size="sm" labelText={t('notif.sound')}
            hideLabel toggled={!muted} onToggle={(on) => setMuted(!on)} />
          <span>{t('notif.sound')}</span>
          <Button kind="ghost" size="sm" data-testid="live-tv-exit" onClick={exit} style={{ marginLeft: 'auto' }}>
            {t('live.tv.exit')}
          </Button>
        </div>
      )}
      <NodeOfflineBanner tv />
      {loadFailed && <p className="lv-tv__msg">{t('common.loadFailed')}</p>}
      {loading ? null : active.length === 0 ? (
        <p className="lv-tv__msg">{cams.length === 0 ? t('live.noCameras') : t('live.noActiveCameras')}</p>
      ) : shown.length === 0 ? (
        <p className="lv-tv__msg" data-testid="live-empty-selection">{t('live.picker.empty')}</p>
      ) : (
        <LiveWall cams={shown} lives={lives} cols={prefs.cols} tv onDebugChange={setDebugOpen} />
      )}
    </div>
  )
}
