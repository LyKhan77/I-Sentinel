import { useEffect, useState } from 'react'
import { InlineNotification } from '@carbon/react'
import { useT } from '../app/i18n'
import { listNodes, type CameraNode } from '../api/cameras'

export const BANNER_POLL_MS = 15_000

/** Banner persisten selama ada node vision offline (AppShell + mode TV). Gagal memuat → tanpa banner. */
export default function NodeOfflineBanner({ tv = false }: { tv?: boolean }) {
  const { t, locale } = useT()
  const [offline, setOffline] = useState<CameraNode[]>([])

  useEffect(() => {
    let alive = true
    const load = () => listNodes()
      .then((ns) => { if (alive) setOffline(ns.filter((n) => n.status === 'offline')) })
      .catch(() => { if (alive) setOffline([]) })
    load()
    const timer = setInterval(load, BANNER_POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  if (offline.length === 0) return null
  return (
    <div className={tv ? 'node-banner node-banner--tv' : 'node-banner'} data-testid="node-offline-banner">
      {offline.map((n) => (
        <InlineNotification key={n.id} kind="error" hideCloseButton lowContrast={!tv}
          title={t('nodeBanner.title').replace('{node}', n.name)}
          subtitle={n.last_seen
            ? t('nodeBanner.since').replace('{time}', new Date(n.last_seen).toLocaleString(locale, { dateStyle: 'short', timeStyle: 'short' }))
            : t('nodeBanner.sub')} />
      ))}
    </div>
  )
}
