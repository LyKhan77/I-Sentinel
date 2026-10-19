import { Button, TextInput } from '@carbon/react'
import { Add, WarningAlt } from '@carbon/icons-react'
import { useT } from '../../app/i18n'
import type { Break } from '../../api/zones'
import { badBreak, buildTimeline } from './breakTimeline'

const ACTIVE = 'var(--cds-support-info)'
const TRACK = 'var(--cds-layer-accent)'
const QUIET = `repeating-linear-gradient(45deg, var(--cds-support-warning), var(--cds-support-warning) 3px, ${TRACK} 3px, ${TRACK} 6px)`
const small = { fontSize: 12, color: 'var(--cds-text-secondary)' } as const

type Props = {
  breaks: Break[]
  /** Jam kerja zona (Jam tertentu / jam shift); null = belum diketahui. Diabaikan untuk gate. */
  work: { start: string; end: string } | null
  /** Gate absensi hanya patuh istirahat: jam kerja tidak dipakai, sumbu 24 jam. */
  gate: boolean
  onChange: (next: Break[]) => void
}

/** Editor istirahat zona: bilah waktu (aktif/diam) + pemilih jam bawaan perangkat per istirahat. */
export default function BreakEditor({ breaks, work, gate, onChange }: Props) {
  const { t } = useT()
  const tl = buildTimeline(gate ? null : work, breaks)
  const invalid = breaks.some(badBreak)
  const times = breaks.filter((b) => !badBreak(b)).map((b) => `${b.start}–${b.end}`).join(', ')
  const summary = times ? t('zones.breakQuiet', { times }) : breaks.length ? '' : t(gate ? 'zones.breakNoneGate' : 'zones.breakNone')
  const setAt = (i: number, patch: Partial<Break>) => onChange(breaks.map((b, j) => (j === i ? { ...b, ...patch } : b)))

  return (
    <div data-testid="zone-breaks" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span style={small}>{t('zones.breaks')}</span>

      {breaks.map((b, i) => (
        <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <TextInput
              id={`zone-break-start-${i}`} data-testid={`zone-break-start-${i}`} type="time"
              labelText={t('zones.breakStart')} value={b.start} invalid={badBreak(b)}
              onChange={(e) => setAt(i, { start: e.target.value })}
            />
            <TextInput
              id={`zone-break-end-${i}`} data-testid={`zone-break-end-${i}`} type="time"
              labelText={t('zones.breakEnd')} value={b.end} invalid={badBreak(b)}
              onChange={(e) => setAt(i, { end: e.target.value })}
            />
          </div>
          <div>
            <Button kind="danger--ghost" size="sm" data-testid={`zone-break-remove-${i}`}
              onClick={() => onChange(breaks.filter((_, j) => j !== i))}>
              {t('zones.breakRemove')}
            </Button>
          </div>
        </div>
      ))}

      <div role="img" aria-label={summary || t('zones.breakInvalid')} data-testid="zone-break-bar"
        style={{ position: 'relative', height: 22, background: TRACK }}>
        <div data-testid="zone-break-bar-work"
          style={{ position: 'absolute', top: 0, bottom: 0, left: `${tl.work.left}%`, width: `${tl.work.width}%`, background: ACTIVE }} />
        {tl.quiet.map((q, i) => (
          <div key={i} data-testid={`zone-break-bar-quiet-${i}`}
            style={{ position: 'absolute', top: 0, bottom: 0, left: `${q.left}%`, width: `${q.width}%`, background: QUIET }} />
        ))}
      </div>
      <div style={{ ...small, display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
        <span data-testid="zone-break-axis-from">{tl.fromLabel}</span>
        <span data-testid="zone-break-axis-to">{tl.toLabel}</span>
      </div>
      <div style={{ ...small, display: 'flex', gap: 14, fontSize: 11 }}>
        <span><i style={{ display: 'inline-block', width: 10, height: 10, marginRight: 5, background: ACTIVE }} />{t('zones.breakLegendActive')}</span>
        {tl.quiet.length > 0 && (
          <span><i style={{ display: 'inline-block', width: 10, height: 10, marginRight: 5, background: QUIET }} />{t('zones.breakLegendQuiet')}</span>
        )}
      </div>

      {summary && <p style={{ ...small, margin: 0 }}>{summary}</p>}
      {gate && <p style={{ ...small, margin: 0 }}>{t('zones.breakGateNote')}</p>}
      {tl.outside && (
        <p role="status" style={{ ...small, margin: 0, display: 'flex', gap: 6, alignItems: 'center' }}>
          <WarningAlt size={16} style={{ fill: 'var(--cds-support-warning)', flex: 'none' }} />{t('zones.breakOutside')}
        </p>
      )}
      {invalid && (
        <p role="alert" data-testid="zone-breaks-invalid" style={{ margin: 0, fontSize: 12, color: 'var(--cds-text-error)' }}>
          {t('zones.breakInvalid')}
        </p>
      )}

      {breaks.length === 0 && (
        <div>
          <Button kind="ghost" size="sm" renderIcon={Add} data-testid="zone-break-add"
            onClick={() => onChange([{ start: '12:00', end: '13:00' }])}>
            {t('zones.breakAdd')}
          </Button>
        </div>
      )}
    </div>
  )
}
