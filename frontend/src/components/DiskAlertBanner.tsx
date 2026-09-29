import { InlineNotification } from '@carbon/react'
import { useT } from '../app/i18n'
import type { StorageStats } from '../api/storage'

/** Banner merah saat pemakaian disk ≥ ambang (Storage & Dashboard). */
export default function DiskAlertBanner({ stats }: { stats: StorageStats | null }) {
  const { t } = useT()
  if (!stats?.disk_alert?.over) return null
  return (
    <div data-testid="disk-alert">
      <InlineNotification
        kind="error"
        lowContrast
        hideCloseButton
        title={t('storage.alert.title').replace('{n}', String(Math.round(stats.disk.percent)))}
        subtitle={t('storage.alert.sub').replace('{m}', String(stats.disk_alert.threshold))}
      />
    </div>
  )
}
