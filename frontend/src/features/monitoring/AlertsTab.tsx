import { useEffect, useState } from 'react'
import { Button, InlineNotification, NumberInput, Select, SelectItem, Tag, Toggle } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { ALERTS_POLL_MS, getHealthAlerts, getHealthRules, putHealthRules,
  type HealthAlert, type HealthAlerts, type HealthRule, type HealthRuleEdit } from '../../api/monitoring'

const op = (rule: string) => rule === 'camera_low_fps' ? '<' : ['camera_no_frames', 'mqtt_backlog'].includes(rule) ? '>' : '≥'

/** Health transitions and editable rules; polling is scoped to the active Monitoring tab. */
export default function AlertsTab({ isAdmin }: { isAdmin: boolean }) {
  const { t, locale } = useT()
  const [alerts, setAlerts] = useState<HealthAlerts>({ active: [], recent: [] })
  const [rules, setRules] = useState<HealthRule[]>([])
  const [edit, setEdit] = useState<Record<string, Partial<HealthRuleEdit>>>({})
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    let alive = true
    getHealthRules().then((r) => { if (alive) setRules(r) })
      .catch(() => { if (alive) setError('common.error') })
    let loading = false
    const load = async () => {
      if (loading) return
      loading = true
      try {
        const a = await getHealthAlerts()
        if (alive) { setAlerts(a); setLoadFailed(false); setNow(Date.now()) }
      } catch { if (alive) setLoadFailed(true) }
      finally { loading = false }
    }
    void load()
    const timer = setInterval(load, ALERTS_POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  const change = (rule: string, patch: Partial<HealthRuleEdit>) => {
    setEdit((prev) => ({ ...prev, [rule]: { ...prev[rule], ...patch } }))
    setSaved(false)
    setError('')
  }
  const save = async () => {
    setBusy(true); setSaved(false); setError('')
    try {
      const updated = await putHealthRules(edit)
      setRules(updated); setEdit({}); setSaved(true)
    } catch (e) { setError(e instanceof Error && e.message === 'invalid' ? 'health.invalid' : 'common.error') }
    finally { setBusy(false) }
  }
  const date = (s: string | null) => s ? new Date(s).toLocaleString(locale) : '—'
  const lasted = (a: HealthAlert) => t('health.minutes').replace('{n}', String(Math.max(0,
    Math.floor(((a.resolved_at ? Date.parse(a.resolved_at) : now) - Date.parse(a.started_at)) / 60_000))))
  const label = (rule: string) => t(`health.rule.${rule}` as TKey)
  const cols = (keys: string[]) => keys.map((key) => <th key={key} scope="col">{t(`health.col.${key}` as TKey)}</th>)
  const disabled = !isAdmin || busy

  return <div className="mon-page health-alerts">
    {loadFailed && <InlineNotification kind="error" lowContrast hideCloseButton title={t('mon.error')} />}
    <section className="mon-card" data-testid="alerts-active">
      <header className="mon-card__head"><h3 className="mon-card__title">{t('health.active')}</h3></header>
      {alerts.active.length === 0 ? <p className="en-muted">{t('health.noActive')}</p> : <div className="mon-table-wrap">
        <table className="mon-table"><thead><tr>{cols(['rule', 'target', 'severity', 'value', 'threshold', 'since'])}</tr></thead>
          <tbody>{alerts.active.map((a) => <tr key={a.id} data-testid={`alert-row-${a.id}`}>
            <td>{label(a.rule)}</td><td>{a.label}</td>
            <td><Tag size="sm" type={a.severity === 'critical' ? 'red' : 'warm-gray'} className={`mon-tag mon-tag--${a.severity}`}>
              {t(a.severity === 'critical' ? 'health.sev.critical' : 'health.sev.warning')}</Tag></td>
            <td>{a.value == null ? '—' : `${a.value} ${a.unit}`}</td><td>{op(a.rule)} {a.threshold} {a.unit}</td>
            <td>{date(a.started_at)} · {lasted(a)}</td>
          </tr>)}</tbody></table>
      </div>}
    </section>
    <section className="mon-card" data-testid="alerts-recent">
      <header className="mon-card__head"><h3 className="mon-card__title">{t('health.recent')}</h3></header>
      {alerts.recent.length === 0 ? <p className="en-muted">{t('health.noRecent')}</p> : <div className="mon-table-wrap">
        <table className="mon-table"><thead><tr>{cols(['rule', 'target', 'start', 'end', 'lasted'])}</tr></thead>
          <tbody>{alerts.recent.map((a) => <tr key={a.id}>
            <td>{label(a.rule)}</td><td>{a.label}</td><td>{date(a.started_at)}</td><td>{date(a.resolved_at)}</td><td>{lasted(a)}</td>
          </tr>)}</tbody></table>
      </div>}
    </section>
    <section className="mon-card health-rules">
      <header className="mon-card__head"><div><h3 className="mon-card__title">{t('health.rules')}</h3>
        <p className="mon-card__sub">{t('health.hint')}</p></div></header>
      <div className="mon-table-wrap"><table className="mon-table">
        <thead><tr>{cols(['rule', 'enabled', 'threshold', 'duration', 'severity', 'telegram'])}</tr></thead>
        <tbody>{rules.map((rule) => {
          const r = { ...rule, ...edit[rule.rule] }
          return <tr key={r.rule} data-testid={`rule-row-${r.rule}`}>
            <td>{label(r.rule)} {r.unit && <small>({r.unit})</small>}</td>
            <td><Toggle id={`enabled-${r.rule}`} size="sm" labelText={t('health.col.enabled')} labelA={t('health.off')} labelB={t('health.on')}
              toggled={r.enabled} disabled={disabled} onToggle={(enabled) => change(r.rule, { enabled })} /></td>
            <td><NumberInput id={`threshold-${r.rule}`} size="sm" label={t('health.col.threshold')} min={r.min} max={r.max} step={1}
              value={r.threshold} disabled={disabled} onChange={(_, data) => change(r.rule, { threshold: Number(data.value) })} /></td>
            <td><NumberInput id={`duration-${r.rule}`} size="sm" label={t('health.col.duration')} min={1} max={60} step={1}
              value={r.duration_min} disabled={disabled} onChange={(_, data) => change(r.rule, { duration_min: Number(data.value) })} /></td>
            <td><Select id={`severity-${r.rule}`} size="sm" labelText={t('health.col.severity')} value={r.severity} disabled={disabled}
              onChange={(e) => change(r.rule, { severity: e.target.value as HealthRuleEdit['severity'] })}>
              <SelectItem value="warning" text={t('health.sev.warning')} /><SelectItem value="critical" text={t('health.sev.critical')} />
            </Select></td>
            <td><Toggle id={`telegram-${r.rule}`} size="sm" labelText={t('health.col.telegram')} labelA={t('health.off')} labelB={t('health.on')}
              toggled={r.telegram} disabled={disabled} onToggle={(telegram) => change(r.rule, { telegram })} /></td>
          </tr>
        })}</tbody></table></div>
      {isAdmin && <Button size="sm" data-testid="rules-save" disabled={busy || Object.keys(edit).length === 0} onClick={save}>{t('health.save')}</Button>}
      {saved && <div data-testid="rules-saved"><InlineNotification kind="success" lowContrast hideCloseButton title={t('health.saved')} /></div>}
      {error && <div data-testid="rules-error"><InlineNotification kind="error" lowContrast hideCloseButton title={t(error as TKey)} /></div>}
    </section>
  </div>
}
