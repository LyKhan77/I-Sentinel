import { useState } from 'react'
import { InlineLoading, InlineNotification, Dropdown } from '@carbon/react'
import { useT } from '../../app/i18n'
import LiveWall from './LiveWall'
import { useLiveCameras } from './useLiveCameras'

const COLS_KEY = 'isentinel_live_cols'
const COL_OPTIONS = [3, 2, 4] as const // urutan mockup 02: default dulu

type Cols = (typeof COL_OPTIONS)[number]

function initialCols(): Cols {
  try {
    const v = Number(localStorage.getItem(COLS_KEY))
    return (COL_OPTIONS as readonly number[]).includes(v) ? (v as Cols) : 3
  } catch {
    return 3
  }
}

export default function LiveViewPage() {
  const { t } = useT()
  const { cams, lives, loading, loadFailed, dismissError } = useLiveCameras()
  const [cols, setCols] = useState<Cols>(initialCols)
  const [loc, setLoc] = useState<{ id: string; label: string } | null>(null)

  // Kamera nonaktif tidak punya stream di go2rtc (sync_camera(delete=True) saat
  // disable) → tile-nya selalu 502 dengan badge LIVE yang menyesatkan.
  const active = cams.filter((c) => c.enabled)
  // lokasi kamera unik; item "semua" di depan supaya filter bisa direset
  const allItem = { id: '__all__', label: t('live.allLocations') }
  const locOptions = [
    allItem,
    ...[...new Set(active.map((c) => c.location).filter((l): l is string => !!l))].map((l) => ({ id: l, label: l })),
  ]
  const shown = loc && loc.id !== '__all__' ? active.filter((c) => c.location === loc.label) : active

  const pickCols = (n: Cols) => {
    try {
      localStorage.setItem(COLS_KEY, String(n))
    } catch {
      // storage tidak tersedia: pilihan hanya berlaku di sesi ini
    }
    setCols(n)
  }

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('nav.live')}</h1>
          <p className="app-page__sub">{t('live.sub')}</p>
        </div>
        <div className="lv-chips">
          {COL_OPTIONS.map((n) => (
            <button
              key={n}
              type="button"
              data-testid={`live-cols-${n}`}
              aria-pressed={cols === n}
              className={cols === n ? 'lv-chip lv-chip--sel' : 'lv-chip'}
              onClick={() => pickCols(n)}
            >
              {t('live.cols').replace('{n}', String(n))}
            </button>
          ))}
          <div style={{ width: 200 }}>
            <Dropdown
              id="live-location"
              titleText={t('live.location')}
              hideLabel
              size="sm"
              label={t('live.allLocations')}
              items={locOptions}
              selectedItem={loc}
              onChange={({ selectedItem }) => setLoc(selectedItem ?? null)}
            />
          </div>
        </div>
      </div>
      {loadFailed && (
        <InlineNotification
          kind="error"
          lowContrast
          title={t('common.error')}
          subtitle={t('common.loadFailed')}
          onCloseButtonClick={dismissError}
        />
      )}
      {/* LiveWall selalu terpasang (grid kosong saat loading) agar WS events menyambung
          sebelum tile apa pun ada — urutan koneksi sama dengan sebelum refactor. */}
      {!loading && shown.length === 0 ? (
        <p style={{ color: '#8d8d8d' }}>{cams.length === 0 ? t('live.noCameras') : t('live.noActiveCameras')}</p>
      ) : (
        <>
          {loading && <InlineLoading description={t('common.loading')} />}
          <LiveWall cams={shown} lives={lives} cols={cols} />
        </>
      )}
    </div>
  )
}
