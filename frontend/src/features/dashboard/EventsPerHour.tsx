import { SkeletonText } from '@carbon/react'
import { useT } from '../../app/i18n'
import LineChart, { PALETTE, type ChartSeries } from '../../components/LineChart'
import { dayStart } from '../notifications/labels'
import type { DashboardData } from './useDashboardData'

const HOUR_MS = 3_600_000

/**
 * LineChart 24 jam hari ini (seri total + critical). Hanya jam ≤ `now` yang
 * digambar — tanpa garis nol palsu ke masa depan (§3.3).
 */
export default function EventsPerHour({ data, now = new Date() }: { data: DashboardData; now?: Date }) {
  const { t, locale } = useT()
  const s = data.stats
  if (!s) {
    if (data.loading) {
      return (
        <div className="dash-section" data-testid="dash-hourly">
          <div className="dash-card"><SkeletonText paragraph lineCount={3} width="60%" /></div>
        </div>
      )
    }
    return (
      <div className="dash-section" data-testid="dash-hourly">
        <div className="dash-card">{t('dash.unavailable')}</div>
      </div>
    )
  }
  const from = dayStart(0, now).getTime()
  const hours = Array.from({ length: now.getHours() + 1 }, (_, h) => h)
  const point = (arr: number[]) => (h: number) => ({ t: from + h * HOUR_MS, v: arr[h] ?? 0 })
  const series: ChartSeries[] = [
    { key: 'total', label: t('dash.hourly.total'), color: PALETTE[1], points: hours.map(point(s.by_hour)) },
    { key: 'critical', label: t('dash.hourly.critical'), color: PALETTE[4], points: hours.map(point(s.critical_by_hour)) },
  ]
  return (
    <div className="dash-section" data-testid="dash-hourly">
      <div className="dash-section__head">
        <h3 className="dash-section__title">{t('dash.hourly.title')}</h3>
      </div>
      <div className="dash-card">
        <LineChart title={t('dash.hourly.title')} series={series} from={from} to={from + 24 * HOUR_MS}
          bucketMs={HOUR_MS} yMin={0} digits={0} locale={locale} />
      </div>
    </div>
  )
}
