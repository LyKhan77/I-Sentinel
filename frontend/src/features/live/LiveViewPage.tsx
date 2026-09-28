import { useState } from 'react'
import { Button, InlineLoading, InlineNotification } from '@carbon/react'
import { useT } from '../../app/i18n'
import CameraPicker from './CameraPicker'
import LiveWall from './LiveWall'
import { useLiveCameras } from './useLiveCameras'
import { COL_OPTIONS, selectCameras, useScreenPrefs } from './screenPrefs'

export default function LiveViewPage() {
  const { t } = useT()
  const [prefs, update] = useScreenPrefs('default')
  const [pickerOpen, setPickerOpen] = useState(false)
  const { cams, lives, loading, loadFailed, dismissError } = useLiveCameras()

  // Kamera nonaktif tidak punya stream di go2rtc (sync_camera(delete=True) saat
  // disable) → tile-nya selalu 502 dengan badge LIVE yang menyesatkan.
  const active = cams.filter((c) => c.enabled)
  const shown = selectCameras(active, prefs.cameras)

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('nav.live')}</h1>
          <p className="app-page__sub">{t('live.sub')}</p>
        </div>
        <div className="lv-chips">
          {COL_OPTIONS.map((n) => (
            <button key={n} type="button" data-testid={`live-cols-${n}`} aria-pressed={prefs.cols === n}
              className={prefs.cols === n ? 'lv-chip lv-chip--sel' : 'lv-chip'} onClick={() => update({ cols: n })}>
              {t('live.cols').replace('{n}', String(n))}
            </button>
          ))}
          <CameraPicker cams={active} value={prefs.cameras} onChange={(cameras) => update({ cameras })}
            open={pickerOpen} onOpenChange={setPickerOpen} />
        </div>
      </div>
      {loadFailed && (
        <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={t('common.loadFailed')}
          onCloseButtonClick={dismissError} />
      )}
      {/* LiveWall selalu terpasang (grid kosong saat loading) agar WS events menyambung
          sebelum tile apa pun ada — urutan koneksi sama dengan sebelum refactor Task 3. */}
      {active.length === 0 && !loading ? (
        <p style={{ color: '#8d8d8d' }}>{cams.length === 0 ? t('live.noCameras') : t('live.noActiveCameras')}</p>
      ) : shown.length === 0 && !loading ? (
        <p data-testid="live-empty-selection" style={{ color: '#8d8d8d' }}>
          {t('live.picker.empty')}{' '}
          <Button kind="ghost" size="sm" data-testid="live-empty-open" onClick={() => setPickerOpen(true)}>
            {t('live.picker.title')}
          </Button>
        </p>
      ) : (
        <>
          {loading && <InlineLoading description={t('common.loading')} />}
          <LiveWall cams={shown} lives={lives} cols={prefs.cols} />
        </>
      )}
    </div>
  )
}
