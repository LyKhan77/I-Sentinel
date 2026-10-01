import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Tag } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import type { EventOut } from '../../api/events'
import { eventTitle, eventWhere, sevClass } from '../notifications/labels'

const MAX_ROWS = 8
const pad = (n: number) => String(n).padStart(2, '0')

function isSameDay(ts: string, now: Date): boolean {
  const d = new Date(ts)
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
}

/** Thumbnail snapshot; tanpa file atau gagal muat → placeholder kosong (kelas .ev-thumb--empty). */
function Thumb({ path }: { path: string | null }) {
  const [broken, setBroken] = useState(false)
  if (!path || broken) return <span className="ev-thumb ev-thumb--empty" aria-hidden="true" />
  return <img className="ev-thumb" src={`/api/v1/media/${path}`} alt="" onError={() => setBroken(true)} />
}

/**
 * 8 event terbaru dari `useEventAlerts().recent` (urutan input dipertahankan):
 * thumbnail, judul, lokasi dengan NAMA kamera, Tag severity dengan teks, jam
 * (tanggal bila bukan hari ini). Baris = tautan detail event.
 */
export default function RecentEvents({ events, cameraName, now = new Date() }: {
  events: EventOut[]
  cameraName: (id: number | null) => string
  now?: Date
}) {
  const { t } = useT()
  return (
    <div className="dash-section" data-testid="dash-recent">
      <div className="dash-section__head">
        <h3 className="dash-section__title">{t('dash.recent.title')}</h3>
        <Link className="dash-section__link" to="/events">{t('dash.recent.all')}</Link>
      </div>
      {events.length === 0 ? (
        <div className="dash-card"><p className="dash-muted">{t('dash.noEvents')}</p></div>
      ) : (
        events.slice(0, MAX_ROWS).map((e) => {
          const sev = sevClass(e.severity)
          const d = new Date(e.ts_event)
          const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`
          const when = isSameDay(e.ts_event, now) ? time : `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${time}`
          return (
            <Link className="dash-event" key={e.id} to={`/events?event=${e.id}`}>
              <Thumb path={e.snapshot_path} />
              <span className="dash-event__body">
                <span className="dash-event__title">{eventTitle(e, t)}</span>
                <span className="dash-event__where">{eventWhere(e, t, cameraName)}</span>
              </span>
              <Tag size="sm" type={sev === 'critical' ? 'red' : 'warm-gray'}>{t(`dash.sev.${sev}` as TKey)}</Tag>
              <span className="dash-event__time">{when}</span>
            </Link>
          )
        })
      )}
    </div>
  )
}
