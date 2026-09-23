import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Checkbox,
  Dropdown,
  InlineLoading,
  InlineNotification,
  Modal,
  NumberInput,
  RadioButton,
  RadioButtonGroup,
  Tag,
  TextInput,
  ToastNotification,
  Toggle,
} from '@carbon/react'
import { Delete, Save } from '@carbon/icons-react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras, type Camera } from '../../api/cameras'
import {
  createZone,
  deleteZone,
  listZones,
  updateZone,
  type Behavior,
  type BehaviorKind,
  type Zone,
  type ZoneType,
} from '../../api/zones'
import ZoneEditor, { ZONE_COLOR } from '../../components/ZoneEditor'

const BEHAVIOR_KINDS: BehaviorKind[] = ['intrusion', 'loitering', 'running']
// ponytail: node melewati analyzer running bila speed_limit_mps = 0 → default masuk akal saat dicentang
const DEFAULT_SPEED_MPS = 2

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
  const [allZones, setAllZones] = useState<Zone[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [busy, setBusy] = useState<'save' | 'delete' | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  // toast hilang sendiri; tanpa ini notifikasi menumpuk sampai halaman di-reload
  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(id)
  }, [toast])

  useEffect(() => {
    Promise.all([listCameras(), listZones().catch(() => [])])
      .then(([cs, all]) => {
        setCams(cs)
        setAllZones(all)
        // buka kamera yang sudah punya zona — membuka kamera kosong bikin editor
        // langsung tampil hampa padahal ada zona lain yang siap disunting
        const first = cs.find((c) => all.some((z) => z.camera_id === c.id)) ?? cs[0]
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
        ...(kind === 'running' ? { speed_limit_mps: DEFAULT_SPEED_MPS } : {}),
        ...current,
        ...patch,
      }
    }
    patchSelected({ behaviors: BEHAVIOR_KINDS.map(entry).filter((b): b is Behavior => b !== null) })
  }

  // attendance: satu threshold — kolom zona dan entry behavior dijaga sinkron
  const setAttendanceTrigger = (n: number) =>
    patchSelected({ trigger_seconds: n, behaviors: [{ kind: 'attendance', trigger_seconds: n }] })

  const save = async () => {
    if (!selected || !cam) return
    setError(null)
    setBusy('save')
    const { id, camera_id, camera_name, ...payload } = selected
    try {
      if (id < 0) {
        const created = await createZone(cam.id, payload)
        setZones(zones.map((z) => (z.id === id ? created : z)))
        setSelectedId(created.id)
      } else {
        await updateZone(id, payload)
      }
      setAllZones((prev) => [...prev.filter((z) => z.camera_id !== cam.id), ...zones.filter((z) => z.id > 0)])
      setToast(t('zones.saved'))
    } catch {
      setError(t('zones.saveError'))
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

                {/* jadwal: 24/7 atau jam kerja + hari */}
                <Dropdown
                  id="zone-schedule-mode"
                  titleText={t('zones.schedule')}
                  label={t('events.filterAll')}
                  items={schedItems}
                  selectedItem={selected.schedule ? schedItems[1] : schedItems[0]}
                  onChange={({ selectedItem }) =>
                    selectedItem &&
                    patchSelected({ schedule: selectedItem.id === 'hours' ? { days: [1, 2, 3, 4, 5], start: '08:00', end: '17:00' } : null })
                  }
                />
                {selected.schedule && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <TextInput
                        id="zone-sched-start"
                        labelText={t('zones.start')}
                        value={selected.schedule.start}
                        onChange={(e) => patchSelected({ schedule: { ...selected.schedule!, start: e.target.value } })}
                      />
                      <TextInput
                        id="zone-sched-end"
                        labelText={t('zones.end')}
                        value={selected.schedule.end}
                        onChange={(e) => patchSelected({ schedule: { ...selected.schedule!, end: e.target.value } })}
                      />
                    </div>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {DAYS.map((d) => {
                        const on = selected.schedule!.days.includes(d)
                        return (
                          <Tag
                            key={d}
                            type={on ? 'blue' : 'gray'}
                            filter
                            style={{ cursor: 'pointer' }}
                            onClick={() =>
                              patchSelected({
                                schedule: {
                                  ...selected.schedule!,
                                  days: on ? selected.schedule!.days.filter((x) => x !== d) : [...selected.schedule!.days, d],
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

                <Toggle
                  id="zone-snapshot"
                  labelText={t('zones.snapshot')}
                  toggled={selected.snapshot}
                  onToggle={(v) => patchSelected({ snapshot: v })}
                />
                <Toggle
                  id="zone-clip"
                  labelText={t('zones.clip')}
                  toggled={selected.clip}
                  onToggle={(v) => patchSelected({ clip: v })}
                />
                {selected.type === 'attendance' ? (
                  <NumberInput
                    id="zone-trigger"
                    data-testid="zone-trigger"
                    label={t('zones.trigger')}
                    helperText={t('zones.triggerHint')}
                    min={0}
                    step={1}
                    value={selected.trigger_seconds ?? 0}
                    onChange={(_, state) => {
                      const n = Number(state.value)
                      if (Number.isInteger(n) && n >= 0) setAttendanceTrigger(n)
                    }}
                  />
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
                                label={t('zones.trigger')}
                                helperText={t('zones.triggerHint')}
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
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
                <div>
                  <Toggle id="zone-telegram" labelText={t('zones.telegram')} toggled={false} onToggle={() => {}} disabled />
                  <div style={{ fontSize: 12, color: 'var(--cds-text-helper)', marginTop: 4 }}>{t('zones.telegramFase3')}</div>
                </div>
                <Checkbox
                  id="zone-active"
                  labelText={t('zones.active')}
                  checked={selected.active}
                  onChange={(_, { checked }) => patchSelected({ active: checked })}
                />

                <div style={{ display: 'flex', gap: 8 }}>
                  <Button kind="primary" renderIcon={Save} data-testid="zone-save" disabled={busy !== null} onClick={save}>
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
