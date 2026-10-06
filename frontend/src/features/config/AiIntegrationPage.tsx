import { useEffect, useState } from 'react'
import { Accordion, AccordionItem, Button, InlineNotification, PasswordInput, Tag, TextArea, TextInput, Toggle } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { AiSettingsError, getAiSettings, putAiSettings, testAiSettings, type AiSettings, type AiSettingsPatch, type AiTestResult } from '../../api/aiSettings'

type Field = keyof Omit<AiSettings, 'key_configured' | 'sources' | 'restart_only'>
type Edits = Partial<Record<Field, string | boolean | null>>
const NUMBERS = [
  ['max_tokens', 100, 8000, 1], ['timeout_caption_s', 5, 600, 'any'], ['timeout_ask_s', 5, 600, 'any'],
  ['ask_rate_per_min', 1, 60, 1], ['caption_min_interval_s', 0, 3600, 'any'],
] as const
const LABELS: Record<Field, TKey> = {
  enabled: 'aiint.enabled', api_url: 'aiint.apiUrl', model: 'aiint.model', max_tokens: 'aiint.maxTokens',
  timeout_caption_s: 'aiint.timeoutCaption', timeout_ask_s: 'aiint.timeoutAsk', ask_rate_per_min: 'aiint.askRate',
  caption_min_interval_s: 'aiint.captionInterval', extra_body: 'aiint.extraBody',
}
const SOURCES: Record<'db' | 'env' | 'default', TKey> = {
  db: 'aiint.sourceDb', env: 'aiint.sourceEnv', default: 'aiint.sourceDefault',
}

/** Admin-only form; credentials remain blank on load and are cleared after a successful save. */
export default function AiIntegrationPage() {
  const { t } = useT()
  const [settings, setSettings] = useState<AiSettings | null>(null)
  const [edits, setEdits] = useState<Edits>({})
  const [key, setKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<AiTestResult | null>(null)
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)

  const errorText = (error: unknown): string => {
    if (error instanceof AiSettingsError && error.status === 422) return error.detail ? `${t('aiint.invalid')} (${error.detail})` : t('aiint.invalid')
    return t(error instanceof Error && error.message.endsWith(': 403') ? 'aiint.forbidden' : 'aiint.error')
  }

  useEffect(() => {
    let active = true
    getAiSettings().then(value => { if (active) setSettings(value) }).catch(error => {
      if (active) setMessage({ kind: 'error', text: t(error instanceof Error && error.message.endsWith(': 403') ? 'aiint.forbidden' : 'aiint.error') })
    })
    return () => { active = false }
  }, [t])

  const notification = message && <InlineNotification kind={message.kind} lowContrast title={message.text}
    onCloseButtonClick={() => setMessage(null)} />
  if (!settings) return notification ?? <p>{t('aiint.loading')}</p>

  const original = (field: Field) => field === 'extra_body' ? JSON.stringify(settings.extra_body, null, 2)
    : field === 'enabled' ? settings.enabled : String(settings[field])
  const value = (field: Field) => field in edits ? edits[field] ?? '' : original(field)
  const change = (field: Field, next: string | boolean | null) => {
    setResult(null)
    setEdits(current => {
      const updated = { ...current }
      if (next === original(field)) delete updated[field]
      else updated[field] = next
      return updated
    })
  }
  const source = (field: Field) => <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
    <Tag type={settings.sources[field] === 'db' ? 'blue' : 'gray'}>{t(SOURCES[settings.sources[field] ?? 'default'])}</Tag>
    <Button kind="ghost" size="sm" aria-label={`${t('aiint.reset')}: ${t(LABELS[field])}`} disabled={busy}
      onClick={() => change(field, null)}>{t('aiint.reset')}</Button>
    {edits[field] === null && <span style={{ color: 'var(--cds-text-helper)' }}>{t('aiint.resetPending')}</span>}
  </div>

  const patch = (): AiSettingsPatch | null => {
    const fields: Record<string, unknown> = {}
    for (const [field, raw] of Object.entries(edits)) {
      if (raw === null || raw === '') fields[field] = null
      else if (field === 'enabled') fields[field] = raw
      else if (field === 'api_url' || field === 'model') fields[field] = String(raw).trim() || null
      else if (field === 'extra_body') {
        try {
          const parsed: unknown = JSON.parse(String(raw))
          if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('object required')
          fields[field] = parsed
        } catch {
          setMessage({ kind: 'error', text: t('aiint.jsonError') })
          return null
        }
      } else {
        const number = Number(raw)
        if (!Number.isFinite(number)) {
          setMessage({ kind: 'error', text: t('aiint.invalid') })
          return null
        }
        fields[field] = number
      }
    }
    if (key) fields.api_key = key
    if (clearKey) fields.clear_api_key = true
    return fields as AiSettingsPatch
  }

  const submit = async (test: boolean) => {
    setMessage(null)
    const values = patch()
    if (!values) return
    setBusy(true)
    setResult(null)
    try {
      if (test) setResult(await testAiSettings(values))
      else {
        setSettings(await putAiSettings(values))
        // kunci diketik tetap ada selama Test atau simpan gagal (admin tak perlu mengetik ulang);
        // hanya dikosongkan setelah tersimpan, supaya tidak tertahan di state
        setKey('')
        setEdits({})
        setClearKey(false)
        setMessage({ kind: 'success', text: t('aiint.saved') })
      }
    } catch (error) {
      setMessage({ kind: 'error', text: errorText(error) })
    } finally {
      setBusy(false)
    }
  }

  return <section aria-label={t('aiint.title')} style={{ display: 'flex', flexDirection: 'column', gap: '1rem', width: '100%', maxWidth: 640, minWidth: 0 }}>
    <p>{t('aiint.intro')}</p>
    <h2>{t('aiint.connection')}</h2>
    <Toggle id="llm-enabled" labelText={t('aiint.enabled')} labelA={t('common.off')} labelB={t('common.on')}
      toggled={edits.enabled == null ? settings.enabled : Boolean(edits.enabled)} disabled={busy}
      onToggle={enabled => change('enabled', enabled)} />
    {source('enabled')}
    {(['api_url', 'model'] as const).map(field => <div key={field}>
      <TextInput id={`llm-${field}`} labelText={t(LABELS[field])} value={String(value(field))} disabled={busy}
        autoComplete="off" onChange={event => change(field, event.target.value)} />
      {source(field)}
    </div>)}
    <PasswordInput id="llm-key" labelText={t('aiint.key')} helperText={t('aiint.keyHint')} autoComplete="off"
      value={key} disabled={busy} onChange={event => { setKey(event.target.value); setClearKey(false); setResult(null) }} />
    {settings.key_configured && <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}>
      <span>{clearKey ? t('aiint.clearPending') : t('aiint.keySaved')}</span>
      <Button kind="danger--ghost" size="sm" disabled={busy || clearKey} onClick={() => { setClearKey(true); setKey(''); setResult(null) }}>
        {t('aiint.clearKey')}
      </Button>
    </div>}
    <Accordion>
      <AccordionItem title={t('aiint.advanced')}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', minWidth: 0 }}>
          {NUMBERS.map(([field, min, max, step]) => <div key={field}>
            <TextInput id={`llm-${field}`} type="number" min={min} max={max} step={step} labelText={t(LABELS[field])}
              helperText={`${min}–${max}`} value={String(value(field))} disabled={busy}
              onChange={event => change(field, event.target.value)} />
            {source(field)}
          </div>)}
          <div>
            <TextArea id="llm-extra" labelText={t('aiint.extraBody')} helperText={t('aiint.extraHint')} rows={5}
              value={String(value('extra_body'))} disabled={busy} onChange={event => change('extra_body', event.target.value)} />
            {source('extra_body')}
          </div>
          <p style={{ color: 'var(--cds-text-helper)' }}>{t('aiint.restart').replace('{concurrency}', String(settings.restart_only.concurrency)).replace('{queue}', String(settings.restart_only.queue_max))}</p>
        </div>
      </AccordionItem>
    </Accordion>
    <p style={{ color: 'var(--cds-text-helper)' }}>{t('aiint.resetHint')}</p>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
      <Button disabled={busy || (!Object.keys(edits).length && !key && !clearKey)} onClick={() => void submit(false)}>{t('common.save')}</Button>
      <Button kind="secondary" disabled={busy} onClick={() => void submit(true)}>{t('aiint.test')}</Button>
    </div>
    {busy && <p role="status">{t('aiint.working')}</p>}
    {result && <div role="status" style={{ overflowWrap: 'anywhere' }}>
      <p>{t('aiint.text')}: {t(result.ok ? 'aiint.ok' : 'aiint.failed')} · {t('aiint.vision')}: {t(result.vision_ok ? 'aiint.ok' : 'aiint.failed')} · {result.latency_ms ?? '—'} ms</p>
      {result.model && <p>{t('aiint.model')}: {result.model}</p>}
      {result.error && <p>{result.error}</p>}
    </div>}
    {notification}
  </section>
}
