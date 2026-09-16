import { useCallback, useEffect, useState } from 'react'
import { Button, InlineLoading, InlineNotification, Table, TableBody, TableCell, TableContainer, TableHead, TableHeader, TableRow, Tag } from '@carbon/react'
import { useT } from '../../app/i18n'
import { getMe, type Me } from '../../api/client'
import { getStorageStats, runSweep, type StorageStats, type SweepResult } from '../../api/storage'

// formatBytes mengikuti locale aktif: id-ID → '2,0 kB', en → '2 kB' (Intl memangkas trailing .0)
function formatBytes(n: number, locale: string): string {
  const units = ['B', 'kB', 'MB', 'GB', 'TB']
  let u = 0
  let v = n
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024
    u++
  }
  const num = new Intl.NumberFormat(locale === 'en' ? 'en' : 'id-ID', { maximumFractionDigits: 1 }).format(v)
  return `${num} ${units[u]}`
}

function Tile({ label, value, sub, testId }: { label: string; value: string; sub?: string; testId?: string }) {
  return (
    <div style={{ background: '#262626', border: '1px solid #393939', padding: '14px 16px' }}>
      <div style={{ fontSize: 11, color: '#8d8d8d', letterSpacing: '.32px' }}>{label}</div>
      <div data-testid={testId} style={{ fontSize: 26, fontWeight: 300, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, marginTop: 4, color: '#8d8d8d' }}>{sub}</div>}
    </div>
  )
}

export default function StoragePage() {
  const { t, locale } = useT()
  const [stats, setStats] = useState<StorageStats | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sweeping, setSweeping] = useState<'dry' | 'now' | null>(null)
  const [sweepResult, setSweepResult] = useState<SweepResult | null>(null)

  const isAdmin = me?.role === 'admin'
  const fmt = (n: number) => formatBytes(n, locale)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setStats(await getStorageStats())
    } catch {
      setError(t('common.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null))
    refresh()
  }, [refresh])

  const sweep = async (dryRun: boolean) => {
    setSweeping(dryRun ? 'dry' : 'now')
    setError(null)
    try {
      const result = await runSweep(dryRun)
      setSweepResult(result)
      await refresh()
    } catch {
      setError(t('storage.sweepError'))
    } finally {
      setSweeping(null)
    }
  }

  const kindRows = (
    [
      ['clips', 'storage.kind.clips'],
      ['snapshots', 'storage.kind.snapshots'],
      ['crops', 'storage.kind.crops'],
    ] as const
  ).map(([kind, label]) => ({ kind, label, usage: stats?.kinds[kind] ?? { files: 0, bytes: 0 } }))

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('storage.title')}</h1>
          <p className="app-page__sub">{t('storage.sub')}</p>
        </div>
        {isAdmin && (
          <div style={{ display: 'flex', gap: 8 }}>
            <Button kind="secondary" onClick={() => sweep(true)} disabled={sweeping !== null}>
              {sweeping === 'dry' ? <InlineLoading description={t('common.loading')} /> : t('storage.dryRun')}
            </Button>
            <Button onClick={() => sweep(false)} disabled={sweeping !== null}>
              {sweeping === 'now' ? <InlineLoading description={t('common.loading')} /> : t('storage.runNow')}
            </Button>
          </div>
        )}
      </div>

      {error && <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={error} />}
      {sweepResult && (
        <InlineNotification
          kind={sweepResult.dry_run ? 'info' : 'success'}
          lowContrast
          title={sweepResult.dry_run ? t('storage.dryRun') : t('storage.sweepOk')}
          subtitle={`${sweepResult.files_deleted} ${t('storage.sweepFiles')} · ${fmt(sweepResult.bytes_freed)} · ${sweepResult.events_marked} ${t('storage.lastSweepMarked')} · ${sweepResult.orphans_deleted} ${t('storage.sweepOrphans')}`}
        />
      )}

      {loading && <InlineLoading description={t('common.loading')} />}

      {stats && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 1, background: '#393939', border: '1px solid #393939', marginBottom: 14 }}>
            <Tile label={t('storage.retention')} value={String(stats.retention_days)} testId="storage-retention" />
            <Tile label={t('storage.path')} value={stats.storage_root} />
            <Tile
              label={t('storage.diskUsed')}
              testId="storage-disk-percent"
              value={`${String(Math.round(stats.disk.percent))}%`}
              sub={`${fmt(stats.disk.free)} ${t('storage.diskFree')}`}
            />
          </div>

          <div style={{ height: 4, background: '#393939', marginBottom: 14 }}>
            <div style={{ height: '100%', width: `${Math.min(stats.disk.percent, 100)}%`, background: '#4589ff' }} />
          </div>

          <TableContainer title="" style={{ background: '#262626', border: '1px solid #393939' }}>
            <Table size="sm">
              <TableHead>
                <TableRow>
                  <TableHeader>{t('storage.col.kind')}</TableHeader>
                  <TableHeader>{t('storage.col.files')}</TableHeader>
                  <TableHeader>{t('storage.col.size')}</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {kindRows.map(({ kind, label, usage }) => (
                  <TableRow key={kind}>
                    <TableCell>{t(label)}</TableCell>
                    <TableCell>{usage.files}</TableCell>
                    <TableCell data-testid={`kind-${kind}`}>{fmt(usage.bytes)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <div style={{ background: '#262626', border: '1px solid #393939', padding: '14px 16px', marginTop: 14 }}>
            <div style={{ fontSize: 11, color: '#8d8d8d', letterSpacing: '.32px' }}>{t('storage.lastSweep')}</div>
            {stats.last_sweep ? (
              <div data-testid="storage-last-sweep" style={{ marginTop: 6, fontSize: 13 }}>
                {new Intl.DateTimeFormat(locale === 'en' ? 'en-GB' : 'id-ID', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(stats.last_sweep.at))}
                {stats.last_sweep.dry_run && (
                  <span style={{ marginLeft: 8 }}>
                    <Tag size="sm">DRY RUN</Tag>
                  </span>
                )}
                <div style={{ marginTop: 4, color: '#c6c6c6' }}>
                  {stats.last_sweep.files_deleted} {t('storage.sweepFiles')} · {fmt(stats.last_sweep.bytes_freed)} ·{' '}
                  {stats.last_sweep.events_marked} {t('storage.lastSweepMarked')} · {stats.last_sweep.orphans_deleted}{' '}
                  {t('storage.sweepOrphans')}
                </div>
              </div>
            ) : (
              <div data-testid="storage-last-sweep" style={{ marginTop: 6, color: '#8d8d8d' }}>
                {t('storage.never')}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
