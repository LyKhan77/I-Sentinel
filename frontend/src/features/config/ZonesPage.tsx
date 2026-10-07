import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Checkbox,
  Dropdown,
  InlineLoading,
  InlineNotification,
  Modal,
  NumberInput,
  Select,
  SelectItem,
  RadioButton,
  RadioButtonGroup,
  Tag,
  TextInput,
  ToastNotification,
  TextArea,
  Toggle,
} from '@carbon/react'
import { Delete, Save } from '@carbon/icons-react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras, type Camera } from '../../api/cameras'
import { listShifts, type Shift } from '../../api/employees'
import { getAiStatus, type AiStatus } from '../../api/ai'
import { eventTypeLabel } from '../events/eventTypes'
import {
  createZone,
  deleteZone,
  listZones,
  updateZone,
  type Behavior,
  type Schedule,
  type BehaviorKind,
  type Zone,
  type ZoneType,
} from '../../api/zones'
import ZoneEditor, { ZONE_COLOR } from '../../components/ZoneEditor'

const BEHAVIOR_KINDS: BehaviorKind[] = ['intrusion', 'loitering', 'running', 'idle_zone', 'crowd']
const DEFAULT_SPEED_MPS = 2
const BEHAVIOR_DEFAULTS: Partial<Record<BehaviorKind, Partial<Behavior>>> = {
  running: { speed_limit_mps: DEFAULT_SPEED_MPS },
  // Empty-zone clips are usually uninformative; users can explicitly enable them.
  idle_zone: { trigger_seconds: 300, reminder_minutes: 15, clip: false },
  crowd: { trigger_seconds: 30, min_count: 5, reminder_minutes: 15 },
}

const DAYS = [1, 2, 3, 4, 5, 6, 7] // 1=Senin .. 7=Minggu (backend VALID_DAYS)
const DAY_LABEL: Record<number, TKey> = {
  1: 'zones.day.1',
  2: 'zones.day.2',
  3: 'zones.day.3',
  4: 'zones.day.4',
  5: 'zones.day.5',
  6: 'zones.day.6',
  7: 'zones.day.7',
}

export default function ZonesPage() {
  const { t } = useT()
  const [cams, setCams] = useState<Camera[]>([])
  const [cam, setCam] = useState<{ id: number; label: string } | null>(null)
  const [zones, setZones] = useState<Zone[]>([])
  const [shifts, setShifts] = useState<Shift[]>([])
  const [allZones, setAllZones] = useState<Zone[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [busy, setBusy] = useState<'save' | 'delete' | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null)
  const [showAiDefaults, setShowAiDefaults] = useState(false)

  useEffect(() => {
    let active = true
    getAiStatus().then((value) => { if (active) setAiStatus(value) }).catch(() => {})
    return () => { active = false }
  }, [])

  // toast hilang sendiri; tanpa ini notifikasi menumpuk sampai halaman di-reload
  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(id)
  }, [toast])

  useEffect(() => {
    listShifts().then(setShifts).catch(() => setShifts([]))
    Promise.all([listCameras(), listZones().catch(() => [])])
      .then(([cs, all]) => {
        setCams(cs)
        setAllZones(all)
        // tautan "Atur zona" dari Deteksi & Model: ?camera=<id> memilih kamera itu
        const wanted = Number(new URLSearchParams(window.location.search).get('camera'))
        // buka kamera yang sudah punya zona — membuka kamera kosong bikin editor
        // langsung tampil hampa padahal ada zona lain yang siap disunting
        const first = cs.find((c) => c.id === wanted)
          ?? cs.find((c) => all.some((z) => z.camera_id === c.id)) ?? cs[0]
        if (first) setCam({ id: first.id, label: first.name })
      })
      .catch(() => setError(t('cameras.loadError')))
      .finally(() => setLoading(false))
  }, [t])

  const reload = useCallback(async (cameraId: number) => {
    setZones(await listZones(cameraId).catch(() => []))
    setSelectedId(null)
  }, [])


  useEffect(() => {
    if (cam) reload(cam.id)
  }, [cam, reload])

  const selected = zones.find((z) => z.id === selectedId) ?? null
  // event = bukti visual: behavior aktif wajib Snapshot atau Clip (backend juga menolak 422)
  const noMedia = (b: Behavior) => !(b.snapshot ?? selected?.snapshot ?? true) && !(b.clip ?? selected?.clip ?? true)
  const mediaMissing = selected?.type === 'behavior'
    ? selected.behaviors.filter((b) => (BEHAVIOR_KINDS as string[]).includes(b.kind) && noMedia(b))
    : []

  const patchSelected = (patch: Partial<Zone>) => {
    if (!selected) return
    setZones(zones.map((z) => (z.id === selected.id ? { ...z, ...patch } : z)))
  }

  /** Tambah/ubah/hapus satu behavior; urutan payload mengikuti BEHAVIOR_KINDS. */
  const setBehavior = (kind: BehaviorKind, patch: Partial<Behavior> | null) => {
    if (!selected) return
    const entry = (k: BehaviorKind): Behavior | null => {
      const current = selected.behaviors.find((b) => b.kind === k) ?? null
      if (k !== kind) return current
      if (patch === null) return null
      return {
        kind,
        trigger_seconds: 0,
        ...BEHAVIOR_DEFAULTS[kind],
        ...current,
        ...patch,
      }
    }
    patchSelected({ behaviors: BEHAVIOR_KINDS.map(entry).filter((b): b is Behavior => b !== null) })
  }

  const save = async () => {
    if (!selected || !cam) return
    setError(null)
    setBusy('save')
    const { id, camera_id, camera_name, ...payload } = selected
    const aiFields = selected.type === 'attendance' ? {} : {
      ai_caption: selected.ai_caption ?? false,
      ai_prompt: selected.ai_prompt?.trim() || null,
    }
    try {
      if (id < 0) {
        const created = await createZone(cam.id, { ...payload, ...aiFields })
        setZones(zones.map((z) => (z.id === id ? created : z)))
        setSelectedId(created.id)
      } else {
        await updateZone(id, { ...payload, ...aiFields })
      }
      setAllZones((prev) => [...prev.filter((z) => z.camera_id !== cam.id), ...zones.filter((z) => z.id > 0)])
      setToast(t('zones.saved'))
    } catch (e) {
      // API client melempar `Error('<what> failed: <status>: <detail server>')` (api/zones.ts expectOk)
      const conflict = e instanceof Error && selected.type === 'attendance'
        && e.message.includes('another direction')
      setError(t(conflict ? 'zones.directionConflict' : 'zones.saveError'))
    } finally {
      setBusy(null)
    }
  }

  const remove = async () => {
    if (!selected) return
    setConfirmDelete(false)
    setBusy('delete')
    try {
      if (selected.id > 0) await deleteZone(selected.id)
      setZones(zones.filter((z) => z.id !== selected.id))
      setSelectedId(null)
      setAllZones((prev) => prev.filter((z) => z.id !== selected.id))
      setToast(t('zones.deleted'))
    } catch {
      setError(t('zones.deleteError'))
    } finally {
      setBusy(null)
    }
  }

  const typeItems: { id: ZoneType; label: string }[] = (['attendance', 'behavior'] as ZoneType[]).map((id) => ({
    id,
    label: t(`zones.type.${id}` as TKey),
  }))
  const dirItems = (['entry', 'exit'] as const).map((id) => ({ id, label: t(`zones.dir.${id}` as TKey) }))
  const sevItems = (['warning', 'critical'] as const).map((id) => ({ id, label: t(`zones.sev.${id}` as TKey) }))
  const schedItems = [
    { id: 'always', label: t('zones.sched247') },
    { id: 'hours', label: t('zones.schedHours') },
    { id: 'shift', label: t('zones.schedShift'), disabled: shifts.length === 0 },
  ]

  return (
    <>
      {error && (
        <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={error} onCloseButtonClick={() => setError(null)} />
      )}

      {toast && (
        <div className="toast-stack" data-testid="zone-toast">
          <ToastNotification
            kind="success" lowContrast title={toast} timeout={0}
            onCloseButtonClick={() => setToast(null)}
          />
        </div>
      )}

      {confirmDelete && selected && (
        <Modal
          open danger
          data-testid="zone-delete-confirm"
          modalHeading={t('zones.deleteTitle')}
          primaryButtonText={t('cameras.delete')}
          secondaryButtonText={t('common.cancel')}
          onRequestSubmit={remove}
          onRequestClose={() => setConfirmDelete(false)}
        >
          <p>{t('zones.deleteBody').replace('{name}', selected.name)}</p>
        </Modal>
      )}

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : !cam ? (
        <p style={{ color: '#8d8d8d' }}>{t('cameras.empty')}</p>
      ) : (
        <div className="configuration-zones">
          {/* rail kamera: jumlah zona terlihat tanpa membuka kamera satu per satu */}
          <div className="zone-rail" data-testid="zone-rail" role="listbox" aria-label={t('zones.camera')}>
            {cams.map((c) => {
              const mine = c.id === cam?.id
                ? zones.filter((z) => z.id > 0)
                : allZones.filter((z) => z.camera_id === c.id)
              const types = [...new Set(mine.map((z) => z.type))]
              const cls = ['zone-rail__item']
              if (cam?.id === c.id) cls.push('zone-rail__item--sel')
              if (mine.length === 0) cls.push('zone-rail__item--empty')
              return (
                <button
                  key={c.id}
                  type="button"
                  role="option"
                  aria-selected={cam?.id === c.id}
                  data-testid={`zone-rail-cam-${c.id}`}
                  className={cls.join(' ')}
                  onClick={() => setCam({ id: c.id, label: c.name })}
                >
                  <span className="zone-rail__name">{c.name}</span>
                  <span className="zone-rail__count">{mine.length}</span>
                  {types.length > 0 && (
                    <span className="zone-rail__types">
                      {types.map((tp) => (
                        <span key={tp} className="zone-badge">{t(`zones.type.${tp}` as TKey).toUpperCase()}</span>
                      ))}
                    </span>
                  )}
                </button>
              )
            })}
          </div>

          <div style={{ minWidth: 0, paddingRight: 16 }}>
            <ZoneEditor
              cameraId={cam.id}
              initialZones={zones}
              onChange={setZones}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />

            {/* daftar zona (mockup 06) — klik = pilih, sama seperti klik polygon */}
            <div className="zone-list" data-testid="zone-list">
              {zones.length === 0 ? (
                <p className="zone-list__empty">{t('zones.listEmpty')}</p>
              ) : (
                zones.map((z) => (
                  <button
                    key={z.id}
                    type="button"
                    data-testid={`zone-item-${z.id}`}
                    className={z.id === selectedId ? 'zone-item zone-item--sel' : 'zone-item'}
                    onClick={() => setSelectedId(z.id)}
                  >
                    <span className="zone-item__sw" style={{ background: ZONE_COLOR[z.type] }} />
                    <span className="zone-item__name">{z.name}</span>
                    <span className="zone-badge">{t(`zones.type.${z.type}` as TKey).toUpperCase()}</span>
                    <span className={z.active ? 'zone-badge zone-badge--green' : 'zone-badge'}>
                      {z.active ? t('zones.active') : t('zones.inactive')}
                    </span>
                  </button>
                ))
              )}
            </div>
          </div>

          <div className="configuration-zones__details">
            {selected ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <TextInput
                  id="zone-name"
                  labelText={t('zones.name')}
                  value={selected.name}
                  onChange={(e) => patchSelected({ name: e.target.value })}
                />
                <Dropdown
                  id="zone-type"
                  titleText={t('zones.col.type')}
                  label={t('events.filterAll')}
                  items={typeItems}
                  selectedItem={typeItems.find((i) => i.id === selected.type)}
                  onChange={({ selectedItem }) => {
                    if (!selectedItem) return
                    if (selectedItem.id === 'attendance')
                      patchSelected({
                        type: 'attendance',
                        direction: selected.direction ?? 'entry',
                        behaviors: [{ kind: 'attendance', trigger_seconds: selected.trigger_seconds }],
                      })
                    else
                      patchSelected({
                        type: 'behavior',
                        direction: null,
                        behaviors: selected.behaviors.filter((b) => b.kind !== 'attendance'),
                      })
                  }}
                />
                {selected.type === 'attendance' && (
                  <RadioButtonGroup
                    legendText={t('zones.direction')}
                    name="zone-direction"
                    orientation="vertical"
                    valueSelected={selected.direction ?? undefined}
                    onChange={(v) => patchSelected({ direction: v as 'entry' | 'exit' })}
                  >
                    {dirItems.map((d) => (
                      <RadioButton key={d.id} id={`dir-${d.id}`} labelText={d.label} value={d.id} />
                    ))}
                  </RadioButtonGroup>
                )}
                <Dropdown
                  id="zone-severity"
                  titleText={t('events.col.severity')}
                  label={t('events.filterAll')}
                  items={sevItems}
                  selectedItem={sevItems.find((i) => i.id === selected.severity)}
                  onChange={({ selectedItem }) => selectedItem && patchSelected({ severity: selectedItem.id })}
                />

                {/* Zone schedule: always, manual hours, or a single shift. */}
                <Dropdown
                  id="zone-schedule-mode"
                  titleText={t('zones.schedule')}
                  label={t('events.filterAll')}
                  items={schedItems}
                  selectedItem={schedItems.find((i) => i.id === (!selected.schedule ? 'always' : 'shift_id' in selected.schedule ? 'shift' : 'hours'))}
                  onChange={({ selectedItem }) => {
                    if (!selectedItem || (selectedItem.id === 'shift' && !shifts.length)) return
                    patchSelected({ schedule: selectedItem.id === 'hours'
                      ? { days: [1, 2, 3, 4, 5], start: '08:00', end: '17:00' }
                      : selectedItem.id === 'shift' ? { shift_id: shifts[0].id } : null })
                  }}
                />
                {selected.schedule && 'shift_id' in selected.schedule && (
                  <Select id="zone-sched-shift" labelText={t('zones.shift')} value={selected.schedule.shift_id}
                    onChange={(e) => patchSelected({ schedule: { shift_id: Number(e.target.value) } })}>
                    {shifts.map((s) => <SelectItem key={s.id} value={s.id} text={`${s.name} (${s.start_time}–${s.end_time})`} />)}
                  </Select>
                )}
                {selected.schedule && 'days' in selected.schedule && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <TextInput
                        id="zone-sched-start"
                        labelText={t('zones.start')}
                        value={selected.schedule.start}
                        onChange={(e) => patchSelected({ schedule: { ...(selected.schedule as Schedule), start: e.target.value } })}
                      />
                      <TextInput
                        id="zone-sched-end"
                        labelText={t('zones.end')}
                        value={selected.schedule.end}
                        onChange={(e) => patchSelected({ schedule: { ...(selected.schedule as Schedule), end: e.target.value } })}
                      />
                    </div>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {DAYS.map((d) => {
                        const on = selected.schedule !== null && 'days' in selected.schedule && selected.schedule.days.includes(d)
                        return (
                          <Tag
                            key={d}
                            type={on ? 'blue' : 'gray'}
                            filter
                            style={{ cursor: 'pointer' }}
                            onClick={() =>
                              patchSelected({
                                schedule: {
                                  ...(selected.schedule as Schedule),
                                  days: on ? (selected.schedule as Schedule).days.filter((x) => x !== d)
                                    : [...(selected.schedule as Schedule).days, d],
                                },
                              })
                            }
                          >
                            {t(DAY_LABEL[d])}
                          </Tag>
                        )
                      })}
                    </div>
                  </div>
                )}

                {selected.type === 'attendance' ? (
                  <>
                    <p data-testid="zone-attendance-hint" style={{ fontSize: 12, color: 'var(--cds-text-secondary)', margin: 0 }}>
                      {t('zones.attendanceHint')}
                    </p>
                    <Toggle
                      id="zone-record-attendance"
                      size="sm"
                      labelText={t('zones.record')}
                      toggled={selected.behaviors.find((b) => b.kind === 'attendance')?.record ?? true}
                      onToggle={(v) =>
                        patchSelected({
                          behaviors: selected.behaviors.map((b) => (b.kind === 'attendance' ? { ...b, record: v } : b)),
                        })
                      }
                    />
                    {selected.behaviors.find((b) => b.kind === 'attendance')?.record === false && (
                      <p data-testid="zone-record-off-hint" style={{ fontSize: 12, color: 'var(--cds-text-secondary)', margin: 0 }}>
                        {t('zones.recordOffHint')}
                      </p>
                    )}
                    <Toggle
                      id="zone-telegram-attendance"
                      size="sm"
                      labelText={t('zones.telegram')}
                      toggled={selected.behaviors.find((b) => b.kind === 'attendance')?.telegram ?? selected.telegram}
                      onToggle={(v) =>
                        patchSelected({
                          behaviors: selected.behaviors.map((b) => (b.kind === 'attendance' ? { ...b, telegram: v } : b)),
                        })
                      }
                    />
                    {(selected.behaviors.find((b) => b.kind === 'attendance')?.telegram ?? selected.telegram) && (
                      <Toggle
                        id="zone-telegram-unknown"
                        size="sm"
                        labelText={t('zones.telegramUnknown')}
                        toggled={selected.behaviors.find((b) => b.kind === 'attendance')?.telegram_unknown ?? true}
                        onToggle={(v) =>
                          patchSelected({
                            behaviors: selected.behaviors.map((b) => (b.kind === 'attendance' ? { ...b, telegram_unknown: v } : b)),
                          })
                        }
                      />
                    )}
                  </>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <span style={{ fontSize: 12, color: 'var(--cds-text-secondary)' }}>{t('zones.behaviors')}</span>
                    {BEHAVIOR_KINDS.map((kind) => {
                      const b = selected.behaviors.find((x) => x.kind === kind)
                      return (
                        <div key={kind} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <Checkbox
                            id={`zone-behavior-${kind}`}
                            data-testid={`zone-behavior-${kind}`}
                            labelText={t(`zones.behavior.${kind}` as TKey)}
                            checked={b != null}
                            onChange={(_, { checked }) => setBehavior(kind, checked ? {} : null)}
                          />
                          {b && (
                            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', paddingLeft: 24 }}>
                              <NumberInput
                                id={`zone-trigger-${kind}`}
                                data-testid={`zone-trigger-${kind}`}
                                size="sm"
                                label={t(kind === 'idle_zone' ? 'zones.idleSeconds' : kind === 'crowd' ? 'zones.crowdSeconds' : 'zones.trigger')}
                                helperText={kind === 'idle_zone' || kind === 'crowd' ? undefined : t('zones.triggerHint')}
                                min={0}
                                step={1}
                                value={b.trigger_seconds}
                                onChange={(_, state) => {
                                  const n = Number(state.value)
                                  if (Number.isInteger(n) && n >= 0) setBehavior(kind, { trigger_seconds: n })
                                }}
                              />
                              {kind === 'running' && (
                                <NumberInput
                                  id="zone-speed-running"
                                  data-testid="zone-speed-running"
                                  size="sm"
                                  label={t('zones.speedLimit')}
                                  min={0}
                                  step={0.5}
                                  value={b.speed_limit_mps ?? DEFAULT_SPEED_MPS}
                                  onChange={(_, state) => {
                                    const n = Number(state.value)
                                    if (n >= 0) setBehavior('running', { speed_limit_mps: n })
                                  }}
                                />
                              )}
                              {kind === 'crowd' && (
                                <NumberInput id="zone-min-count" data-testid="zone-min-count" size="sm"
                                  label={t('zones.minCount')} min={1} step={1} value={b.min_count ?? 5}
                                  onChange={(_, state) => {
                                    const n = Number(state.value)
                                    if (Number.isInteger(n) && n >= 1) setBehavior('crowd', { min_count: n })
                                  }} />
                              )}
                              {(kind === 'idle_zone' || kind === 'crowd') && (
                                <NumberInput id={`zone-reminder-${kind}`} data-testid={`zone-reminder-${kind}`} size="sm"
                                  label={t('zones.reminder')} helperText={t('zones.reminderHint')} min={0} step={1}
                                  value={b.reminder_minutes ?? 15}
                                  onChange={(_, state) => {
                                    const n = Number(state.value)
                                    if (Number.isInteger(n) && n >= 0) setBehavior(kind, { reminder_minutes: n })
                                  }} />
                              )}
                              <Toggle
                                id={`zone-snapshot-${kind}`}
                                size="sm"
                                labelText={t('zones.snapshot')}
                                toggled={b.snapshot ?? selected.snapshot}
                                onToggle={(v) => setBehavior(kind, { snapshot: v })}
                              />
                              <Toggle
                                id={`zone-clip-${kind}`}
                                size="sm"
                                labelText={t('zones.clip')}
                                toggled={b.clip ?? selected.clip}
                                onToggle={(v) => setBehavior(kind, { clip: v })}
                              />
                              <Toggle
                                id={`zone-telegram-${kind}`}
                                size="sm"
                                labelText={t('zones.telegram')}
                                toggled={b.telegram ?? selected.telegram}
                                onToggle={(v) => setBehavior(kind, { telegram: v })}
                              />
                            </div>
                          )}
                          {b && noMedia(b) && (
                            <p role="alert" data-testid={`zone-media-warning-${kind}`}
                              style={{ margin: '0 0 0 24px', fontSize: 12, color: 'var(--cds-text-error)' }}>
                              {t('zones.mediaRequired')}
                            </p>
                          )}
                        </div>
                      )
                    })}
                    <Toggle
                      id="zone-ai-caption" size="sm"
                      labelText={t('zones.aiCaption')}
                      labelA={t('common.off')} labelB={t('common.on')}
                      toggled={selected.ai_caption ?? false}
                      onToggle={(value) => patchSelected({ ai_caption: value })}
                    />
                    {selected.ai_caption && (
                      <>
                        <RadioButtonGroup
                          name="zone-ai-mode" legendText={t('zones.aiPrompt.mode')}
                          valueSelected={selected.ai_prompt == null ? 'default' : 'custom'}
                          onChange={(value) => patchSelected({ ai_prompt: value === 'default' ? null : '' })}
                        >
                          <RadioButton id="zone-ai-default" value="default" labelText={t('zones.aiPrompt.default')} />
                          <RadioButton id="zone-ai-custom" value="custom" labelText={t('zones.aiPrompt.custom')} />
                        </RadioButtonGroup>
                        {selected.ai_prompt != null && (
                          <TextArea
                            id="zone-ai-prompt" labelText={t('zones.aiPrompt.label')}
                            placeholder={t('zones.aiPrompt.placeholder')} maxLength={600}
                            helperText={`${selected.ai_prompt.length}/600`}
                            value={selected.ai_prompt}
                            onChange={(e) => patchSelected({ ai_prompt: e.target.value })}
                          />
                        )}
                        {aiStatus && (
                          <Button kind="ghost" size="sm" onClick={() => setShowAiDefaults(true)}>
                            {t('zones.aiPrompt.defaults')}
                          </Button>
                        )}
                      </>
                    )}
                  </div>
                )}
                {showAiDefaults && aiStatus && (
                  <Modal open passiveModal modalHeading={t('zones.aiPrompt.defaults')} onRequestClose={() => setShowAiDefaults(false)}>
                    {Object.entries(aiStatus.caption_prompts).map(([kind, prompt]) => (
                      <p key={kind}><strong>{eventTypeLabel(kind, t)}</strong><br /><span>{prompt}</span></p>
                    ))}
                  </Modal>
                )}
                <Checkbox
                  id="zone-active"
                  labelText={t('zones.active')}
                  checked={selected.active}
                  onChange={(_, { checked }) => patchSelected({ active: checked })}
                />

                <div style={{ display: 'flex', gap: 8 }}>
                  <Button kind="primary" renderIcon={Save} data-testid="zone-save" disabled={busy !== null || mediaMissing.length > 0} onClick={save}>
                    {busy === 'save' ? t('common.saving') : t('common.save')}
                  </Button>
                  <Button
                    kind="danger--ghost" renderIcon={Delete} data-testid="zone-delete"
                    disabled={busy !== null} onClick={() => setConfirmDelete(true)}
                  >
                    {busy === 'delete' ? t('common.deleting') : t('cameras.delete')}
                  </Button>
                </div>
              </div>
            ) : (
              <p style={{ color: 'var(--cds-text-helper)' }}>{t('zones.selectHint')}</p>
            )}
          </div>
        </div>
      )}
    </>
  )
}
