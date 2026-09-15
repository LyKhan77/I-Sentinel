import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Checkbox,
  Dropdown,
  InlineLoading,
  InlineNotification,
  RadioButton,
  RadioButtonGroup,
  Tag,
  TextInput,
  Toggle,
} from '@carbon/react'
import { Delete, Save } from '@carbon/icons-react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras, type Camera } from '../../api/cameras'
import { createZone, deleteZone, listZones, updateZone, type Zone, type ZoneType as ZT } from '../../api/zones'
import ZoneEditor from '../../components/ZoneEditor'

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
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listCameras()
      .then((cs) => {
        setCams(cs)
        if (cs.length > 0) setCam({ id: cs[0].id, label: cs[0].name })
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

  const save = async () => {
    if (!selected || !cam) return
    setError(null)
    const { id, camera_id, camera_name, ...payload } = selected
    try {
      if (id < 0) {
        const created = await createZone(cam.id, payload)
        setZones(zones.map((z) => (z.id === id ? created : z)))
        setSelectedId(created.id)
      } else {
        await updateZone(id, payload)
      }
    } catch {
      setError(t('zones.saveError'))
    }
  }

  const remove = async () => {
    if (!selected) return
    try {
      if (selected.id > 0) await deleteZone(selected.id)
      setZones(zones.filter((z) => z.id !== selected.id))
      setSelectedId(null)
    } catch {
      setError(t('zones.saveError'))
    }
  }

  const typeItems: { id: ZT; label: string }[] = (['restricted', 'absensi', 'free'] as ZT[]).map((id) => ({
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
    <div style={{ padding: 32, maxWidth: 1200 }}>
      <h1 style={{ fontWeight: 300, margin: 0, marginBottom: 16 }}>{t('zones.title')}</h1>

      <div style={{ maxWidth: 360, marginBottom: 16 }}>
        <Dropdown
          id="zone-camera"
          titleText={t('zones.camera')}
          label={t('events.filterAll')}
          items={cams.map((c) => ({ id: c.id, label: c.name }))}
          selectedItem={cam}
          onChange={({ selectedItem }) => selectedItem && setCam(selectedItem)}
        />
      </div>

      {error && (
        <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={error} onCloseButtonClick={() => setError(null)} />
      )}

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : !cam ? (
        <p style={{ color: '#8d8d8d' }}>{t('cameras.empty')}</p>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(280px, 1fr)', gap: 24 }}>
          <ZoneEditor
            cameraId={cam.id}
            initialZones={zones}
            onChange={setZones}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />

          <div>
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
                  onChange={({ selectedItem }) =>
                    selectedItem && patchSelected({ type: selectedItem.id, direction: selectedItem.id === 'absensi' ? selected.direction : null })
                  }
                />
                {selected.type === 'absensi' && (
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
                  <Button kind="primary" renderIcon={Save} data-testid="zone-save" onClick={save}>
                    {t('common.save')}
                  </Button>
                  <Button kind="danger--ghost" renderIcon={Delete} data-testid="zone-delete" onClick={remove}>
                    {t('cameras.delete')}
                  </Button>
                </div>
              </div>
            ) : (
              <p style={{ color: 'var(--cds-text-helper)' }}>{t('zones.selectHint')}</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
