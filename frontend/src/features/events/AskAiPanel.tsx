import { useEffect, useState } from 'react'
import { Button, InlineLoading, InlineNotification, Tag, TextArea } from '@carbon/react'
import { AiError, askEvent, getEventAi, type AiStatus, type AiTurn, type EventAi } from '../../api/ai'
import type { EventOut } from '../../api/events'
import { useT, type TKey } from '../../app/i18n'

type PanelProps = { event: EventOut; status: AiStatus; tick: number }
type Turn = AiTurn & { frames: number; cached: boolean }

/** Key the conversation by event so questions and in-flight results cannot cross events. */
export default function AskAiPanel(props: PanelProps) {
  if (!props.status.enabled || props.event.type === 'attendance' || props.event.type === 'system') return null
  return <Conversation key={props.event.id} {...props} />
}

function Conversation({ event, status, tick }: PanelProps) {
  const { t } = useT()
  const [data, setData] = useState<EventAi | null>(null)
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TKey | null>(null)
  const [goneKey, setGoneKey] = useState<TKey | null>(null)
  // backend selalu butuh snapshot: event hanya-klip (zona snapshot=false) tidak bisa ditanya
  const clipOnly = !event.snapshot_path && !!event.clip_path
  const unavailable = goneKey !== null || !event.snapshot_path
  const unavailableKey: TKey = goneKey ?? (clipOnly ? 'ai.err.snapshot' : 'ai.err.mediaExpired')
  const disabled = busy || unavailable || !status.enabled

  useEffect(() => {
    let alive = true
    getEventAi(event.id).then((value) => { if (alive) setData(value) })
      .catch(() => { if (alive) setError('ai.err.generic') })
    return () => { alive = false }
  }, [event.id, tick])

  const send = async (preset?: string) => {
    if (disabled || (!preset && !question.trim())) return
    const q = preset ? t(`ai.preset.${preset}` as TKey) : question.trim()
    setBusy(true)
    setError(null)
    try {
      const reply = await askEvent(event.id, {
        ...(preset ? { preset } : { question: question.trim() }),
        history: turns.slice(-6).map(({ q, a }) => ({ q: q.slice(0, 2000), a: a.slice(0, 2000) })),
      })
      setTurns((prev) => [...prev, { q, a: reply.answer, frames: reply.frames_used, cached: reply.cached }])
      setQuestion('')
    } catch (e) {
      let key: TKey = 'ai.err.generic'
      if (e instanceof AiError) {
        if (e.status === 429) key = 'ai.err.rate'
        else if (e.code === 'disabled') key = 'ai.err.disabled'
        else if (e.status === 503) key = 'ai.err.busy'
        else if (e.code === 'media_expired' || e.code === 'snapshot_unavailable') {
          key = e.code === 'media_expired' ? 'ai.err.mediaExpired' : 'ai.err.snapshot'
          setGoneKey(key)
        } else if (e.code === 'clip_unavailable') key = 'ai.err.clip'
      }
      setError(key)
    } finally {
      setBusy(false)
    }
  }
  const caption = data?.caption
  const saved = (data?.history ?? []).filter((row) => row.answer && !turns.some((turn) => turn.a === row.answer
    && turn.q === (row.question ?? (row.preset ? t(`ai.preset.${row.preset}` as TKey) : '')))).slice().reverse()

  return (
    <section className="ev-ai" aria-label={t('ai.title')}>
      <div className="ev-ai__head"><h3>{t('ai.title')}</h3><Tag type="purple">{t('ai.badge')}</Tag></div>
      <div className="ev-ai__caption" aria-live="polite">
        {caption?.status === 'ok' ? <p>{caption.answer}</p>
          : <p>{t(caption?.status === 'pending' ? 'ai.caption.pending' : caption?.status === 'failed' ? 'ai.caption.failed' : 'ai.caption.empty')}</p>}
      </div>
      <p className="ev-ai__hint">{t('ai.warn.smallObjects')}</p>
      {unavailable && !error && <p className="ev-ai__hint">{t(unavailableKey)}</p>}
      <div className="ev-ai__presets">
        {(status.presets[event.type] ?? []).map((preset) => (
          <Button key={preset} kind="tertiary" size="sm" disabled={disabled} onClick={() => send(preset)}>
            {t(`ai.preset.${preset}` as TKey)}
          </Button>
        ))}
      </div>
      <TextArea id={`ai-question-${event.id}`} labelText={t('ai.ask.label')} placeholder={t('ai.ask.placeholder')}
        maxLength={500} value={question} disabled={disabled} onChange={(e) => setQuestion(e.target.value)} />
      <Button size="sm" disabled={disabled || !question.trim()} onClick={() => send()}>{t('ai.ask.send')}</Button>
      {busy && <InlineLoading description={t('ai.ask.thinking')} />}
      {error && <InlineNotification kind="error" lowContrast hideCloseButton title={t('common.error')} subtitle={t(error)} />}
      <div className="ev-ai__thread" aria-live="polite">
        {saved.map((row) => <div key={row.id} className="ev-ai__turn"><strong>{row.question ?? (row.preset ? t(`ai.preset.${row.preset}` as TKey) : '')}</strong><p>{row.answer}</p></div>)}
        {turns.map((turn, i) => (
          <div key={i} className="ev-ai__turn"><strong>{turn.q}</strong><p>{turn.a}</p>
            <p className="ev-ai__hint">{t('ai.frames').replace('{n}', String(turn.frames))}{turn.cached ? ` · ${t('ai.cached')}` : ''}</p>
            {turn.frames === 0 && <p className="ev-ai__hint">{t('ai.snapshotOnly')}</p>}
          </div>
        ))}
      </div>
    </section>
  )
}
