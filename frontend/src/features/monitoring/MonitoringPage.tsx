import { useEffect, useState, type ReactNode } from 'react'
import { InlineNotification, Tag, Toggle } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { getMonitoring, type Health, type HostStats, type MonCamera, type Monitoring } from '../../api/monitoring'
import { ago, fmt, HEALTH_ORDER, healthKey, issueKey, serviceKey, stateKey } from './health'

export const POLL_MS = 10_000
const TAG: Record<Health, 'green' | 'warm-gray' | 'red' | 'gray' | 'cool-gray'> = {
  ok: 'green', warning: 'warm-gray', critical: 'red', unknown: 'gray', disabled: 'cool-gray',
}

function HealthTag({ h }: { h: Health }) {
  const { t } = useT()
  return <Tag type={TAG[h]} size="sm" className={`mon-tag mon-tag--${h}`}>{t(healthKey(h))}</Tag>
}

function HostLines({ host }: { host: HostStats }) {
  const { t } = useT()
  const ram = host.ram_used_mb != null && host.ram_total_mb
    ? `${(host.ram_used_mb / 1024).toFixed(1)} / ${(host.ram_total_mb / 1024).toFixed(1)} GB` : '—'
  return (
    <dl className="mon-kv">
      <dt>{t('mon.cpu')}</dt><dd>{fmt(host.cpu_pct, ' %')}</dd>
      <dt>{t('mon.ram')}</dt><dd>{ram}</dd>
      <dt>{t('mon.disk')}</dt><dd>{fmt(host.disk_used_pct, ' %')} · {fmt(host.disk_free_gb, ' GB', 1)}</dd>
    </dl>
  )
}

/** Blok berjudul kecil di dalam kartu node (Hardware / GPU / Inferensi / Masalah). */
function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mon-group">
      <h4 className="mon-group__title">{title}</h4>
      {children}
    </div>
  )
}

/** System › Monitoring: kondisi saat ini (S1). Polling 10 s; gagal → data terakhir tetap tampil. */
export default function MonitoringPage() {
  const { t, locale } = useT()
  const [data, setData] = useState<Monitoring | null>(null)
  const [failed, setFailed] = useState(false)
  const [onlyIssues, setOnlyIssues] = useState(false)

  useEffect(() => {
    let alive = true
    const load = () => getMonitoring()
      .then((d) => { if (alive) { setData(d); setFailed(false) } })
      .catch(() => { if (alive) setFailed(true) })
    load()
    const timer = setInterval(load, POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  const cams: MonCamera[] = (data?.cameras ?? [])
    .filter((c) => !onlyIssues || c.health === 'warning' || c.health === 'critical')
    .sort((a, b) => HEALTH_ORDER[a.health] - HEALTH_ORDER[b.health] || a.name.localeCompare(b.name))

  return (
    <div className="mon-page">
      <header className="mon-header">
        <h1 className="mon-title">{t('mon.title')}</h1>
        <p className="en-muted">{t('mon.subtitle')}</p>
      </header>
      {failed && <div data-testid="mon-error"><InlineNotification kind="error" lowContrast hideCloseButton title={t('mon.error')} /></div>}
      {data && (
        <>
          <section className="mon-summary" data-testid="mon-summary">
            <div className={`mon-tile mon-tile--${data.summary.health}`}>
              <span>{t('mon.overall')}</span>
              <strong>{t(healthKey(data.summary.health))}</strong>
              <small>{t('mon.updated').replace('{time}', new Date(data.generated_at).toLocaleTimeString(locale))}</small>
            </div>
            {(['cameras', 'nodes', 'services'] as const).map((k) => (
              <div key={k} className="mon-tile">
                <span>{t(`mon.${k}` as TKey)}</span>
                <strong>{data.summary[k].ok}</strong>
                <small>
                  {t('mon.health.warning')} {data.summary[k].warning} · {t('mon.health.critical')} {data.summary[k].critical}
                </small>
              </div>
            ))}
          </section>

          <section className="mon-nodes">
            {data.nodes.length === 0 && <p className="en-muted">{t('mon.noNodes')}</p>}
            {data.nodes.map((n) => (
              <article key={n.id} className="mon-card" data-testid={`mon-node-${n.id}`}>
                <header className="mon-card__head">
                  <div>
                    <h3 className="mon-card__title">{n.name}</h3>
                    {n.age_s != null && (
                      <p className="mon-card__sub">{t('mon.heartbeat').replace('{ago}', ago(n.age_s, t))}</p>
                    )}
                  </div>
                  <HealthTag h={n.health} />
                </header>
                <Group title={t('mon.group.host')}><HostLines host={n.host} /></Group>
                {n.gpus.map((g) => (
                  <Group key={g.idx ?? 0} title={`${t('mon.gpu')} ${g.idx ?? ''}`}>
                    <dl className="mon-kv">
                      <dt>{t('mon.gpu')}</dt><dd>{g.name ?? '—'} · {fmt(g.util_pct, ' %')}</dd>
                      <dt>{t('mon.vram')}</dt><dd>{fmt(g.vram_used_mb)} / {fmt(g.vram_total_mb, ' MB')}</dd>
                      <dt>{t('mon.temp')}</dt><dd>{fmt(g.temp_c, ' °C')} · {fmt(g.power_w, ' W')}</dd>
                    </dl>
                  </Group>
                ))}
                <Group title={t('mon.group.infer')}>
                  <dl className="mon-kv">
                    <dt>{t('mon.infer')}</dt>
                    <dd>{n.inference.detector.model ?? '—'} · {n.inference.detector.device ?? '—'}</dd>
                    <dt>{t('mon.inferMs')}</dt>
                    <dd>{fmt(n.inference.detector.ms_avg, '', 1)} / {fmt(n.inference.detector.ms_max, ' ms', 1)}</dd>
                    <dt>{t('mon.inferFps')}</dt><dd>{fmt(n.inference.detector.infer_fps, '', 1)}</dd>
                    <dt>{t('mon.faceQueue')}</dt><dd>{fmt(n.inference.face.queue)}</dd>
                    <dt>{t('mon.backlog')}</dt><dd>{fmt(n.inference.mqtt_backlog)}</dd>
                  </dl>
                </Group>
                {n.issues.length > 0 && (
                  <Group title={t('mon.group.issues')}>
                    <ul className="mon-issues">{n.issues.map((i) => <li key={i}>{t(issueKey(i))}</li>)}</ul>
                  </Group>
                )}
              </article>
            ))}
            <article className="mon-card" data-testid="mon-server">
              <header className="mon-card__head">
                <h3 className="mon-card__title">{t('mon.server')}</h3>
              </header>
              <Group title={t('mon.group.host')}><HostLines host={data.server} /></Group>
            </article>
          </section>

          <section className="mon-card">
            <header className="mon-card__head">
              <h3 className="mon-card__title">{t('mon.cameras')}</h3>
              <Toggle id="mon-only-issues" size="sm" labelText={t('mon.onlyIssues')}
                toggled={onlyIssues} onToggle={setOnlyIssues} />
            </header>
            {cams.length === 0 ? <p className="en-muted">{t('mon.noCameras')}</p> : (
              <div className="mon-table-wrap">
                <table className="mon-table">
                  <thead>
                    <tr>
                      {(['name', 'location', 'node', 'health', 'state', 'fps', 'age', 'reconnects', 'skip', 'stream'] as const)
                        .map((c) => <th key={c}>{t(`mon.col.${c}` as TKey)}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {cams.map((c) => (
                      <tr key={c.id} data-testid={`mon-cam-${c.id}`}>
                        <td>{c.name}</td>
                        <td>{c.location ?? '—'}</td>
                        <td>{c.node_name ?? '—'}</td>
                        <td>
                          <HealthTag h={c.health} />
                          {c.issues.length > 0 && (
                            <span className="mon-issue">{c.issues.map((i) => t(issueKey(i))).join(' · ')}</span>
                          )}
                        </td>
                        <td>{c.ai ? t(stateKey(c.ai.state)) : c.analyzed ? '—' : t('mon.state.idle')}</td>
                        <td>{c.ai ? `${fmt(c.ai.fps, '', 1)} / ${fmt(c.ai.target_fps, '', 1)}` : '—'}</td>
                        <td>{c.ai ? fmt(c.ai.last_frame_age_s, ' s', 1) : '—'}</td>
                        <td>{c.ai ? c.ai.reconnects_1h : '—'}</td>
                        <td>{c.ai ? fmt(c.ai.motion_skip_pct, ' %') : '—'}</td>
                        <td>{c.stream.registered == null ? '—' : t(c.stream.registered ? 'mon.stream.yes' : 'mon.stream.no')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="mon-card">
            <header className="mon-card__head">
              <h3 className="mon-card__title">{t('mon.services')}</h3>
            </header>
            <ul className="mon-services">
              {data.services.map((s) => (
                <li key={s.key} data-testid={`mon-svc-${s.key}`}>
                  <span className="mon-services__name">{t(serviceKey(s.key))}</span>
                  <HealthTag h={s.health} />
                  <span className="mon-services__detail">{[s.detail, s.latency_ms != null ? `${s.latency_ms} ms` : null].filter(Boolean).join(' · ')}</span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}
