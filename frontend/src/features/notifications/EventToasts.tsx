import { useNavigate } from 'react-router-dom'
import { ToastNotification } from '@carbon/react'
import { useT } from '../../app/i18n'
import { useEventAlerts } from './EventAlertsProvider'
import { eventWhere, sevClass, typeKey } from './labels'

export const TOAST_MS = 8000
const TOAST_KIND = { critical: 'error', warning: 'warning', info: 'info' } as const

/** Toast event baru (kanan atas). Klik isi → detail event; tombol × hanya menutup. */
export default function EventToasts() {
  const { t, locale } = useT()
  const navigate = useNavigate()
  const { toasts, dismissToast, cameraName } = useEventAlerts()
  if (toasts.length === 0) return null
  return (
    <div className="nt-toasts" data-testid="event-toasts">
      {toasts.map((e) => (
        <div key={e.id} data-testid={`toast-${e.id}`} className="nt-toasts__item"
          onClick={(ev) => {
            // klik tombol tutup hanya menutup, tidak ikut membuka detail event
            if (ev.target instanceof Element && ev.target.closest('button')) return
            dismissToast(e.id)
            navigate(`/events?event=${e.id}`)
          }}>
          <ToastNotification kind={TOAST_KIND[sevClass(e.severity)]} lowContrast timeout={TOAST_MS}
            title={t(typeKey(e.type))} subtitle={eventWhere(e, t, cameraName)}
            caption={new Date(e.ts_event).toLocaleTimeString(locale)}
            onClose={() => { dismissToast(e.id) }} />
        </div>
      ))}
    </div>
  )
}
