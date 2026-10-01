import { useT } from '../../app/i18n'
import DiskAlertBanner from '../../components/DiskAlertBanner'
import { useEventAlerts } from '../notifications/EventAlertsProvider'
import ActiveIssues from './ActiveIssues'
import EventsPerHour from './EventsPerHour'
import KpiTiles from './KpiTiles'
import NodeCompact from './NodeCompact'
import RecentEvents from './RecentEvents'
import StatusStrip from './StatusStrip'
import { useDashboardData } from './useDashboardData'

/**
 * Dashboard status-first: strip status → 4 tile tautan → chart event per jam →
 * (event terbaru | masalah aktif + node ringkas). Data dari useDashboardData
 * (polling 15 dtk, kegagalan per sumber) + useEventAlerts (satu langganan
 * realtime app-wide — tidak ada langganan kedua di sini).
 */
export default function DashboardPage() {
  const { t } = useT()
  const { recent, cameraName } = useEventAlerts()
  const data = useDashboardData(recent[0]?.id ?? null)
  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('nav.dashboard')}</h1>
          <p className="app-page__sub">{t('dash.sub')}</p>
        </div>
      </div>
      <DiskAlertBanner stats={data.storage} />
      <StatusStrip data={data} />
      <KpiTiles data={data} />
      <EventsPerHour data={data} />
      <div className="dash-grid">
        <RecentEvents events={recent} cameraName={cameraName} />
        <div className="dash-side">
          <ActiveIssues data={data} />
          <NodeCompact data={data} />
        </div>
      </div>
    </div>
  )
}
