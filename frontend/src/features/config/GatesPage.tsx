import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button,
  InlineLoading,
  InlineNotification,
  Select,
  SelectItem,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  Tag,
  Toggle,
} from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras, type Camera } from '../../api/cameras'
import { createZone, listZones, updateZone, type Zone } from '../../api/zones'

// ponytail: default polygon kotak — admin menggambar ulang di editor zona
const DEFAULT_POLYGON: [number, number][] = [
  [0.1, 0.1],
  [0.9, 0.1],
  [0.9, 0.9],
  [0.1, 0.9],
]

export default function GatesPage() {
  const { t } = useT()
  const navigate = useNavigate()
  const [zones, setZones] = useState<Zone[]>([])
  const [cams, setCams] = useState<Camera[]>([])
  const [newCamId, setNewCamId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [zs, cs] = await Promise.all([listZones(), listCameras()])
      const enabled = cs.filter((c) => c.enabled)
      setCams(enabled)
      setZones(zs.filter((z) => z.type === 'absensi'))
      if (enabled.length > 0) setNewCamId((prev) => prev ?? enabled[0].id)
    } catch {
      setError(t('gates.loadError'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    load()
  }, [load])

  const camName = (id: number) => cams.find((c) => c.id === id)?.name ?? zones.find((z) => z.camera_id === id)?.camera_name ?? `#${id}`

  const patch = async (zone: Zone, body: { direction?: 'entry' | 'exit'; snapshot?: boolean; active?: boolean }) => {
    try {
      const updated = await updateZone(zone.id, body)
      setZones((cur) => cur.map((z) => (z.id === zone.id ? updated : z)))
    } catch {
      setError(t('gates.saveError'))
    }
  }

  // konflik: satu kamera punya >1 zona absensi aktif dengan arah berbeda
  const conflicted = new Set<number>()
  const byCam = new Map<number, Zone[]>()
  for (const z of zones.filter((z) => z.active)) {
    byCam.set(z.camera_id, [...(byCam.get(z.camera_id) ?? []), z])
  }
  for (const [cam, list] of byCam) {
    if (new Set(list.map((z) => z.direction)).size > 1) conflicted.add(cam)
  }

  const addGate = async () => {
    if (newCamId == null) return
    try {
      await createZone(newCamId, {
        name: `Gate ${camName(newCamId)}`,
        type: 'absensi',
        direction: 'entry',
        polygon: DEFAULT_POLYGON,
        snapshot: true,
        active: true,
      })
      navigate('/config/zones')
    } catch {
      setError(t('gates.saveError'))
    }
  }

  const headers: TKey[] = ['gates.col.camera', 'gates.col.direction', 'gates.col.snapshot', 'gates.col.active']

  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <h1 style={{ fontWeight: 300, margin: 0, marginBottom: 16 }}>{t('gates.title')}</h1>

      {error && <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={error} onCloseButtonClick={() => setError(null)} />}

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', marginBottom: 14 }}>
        <div style={{ width: 260 }}>
          <Select id="gate-cam" labelText={t('gates.col.camera')} value={newCamId ?? ''} onChange={(e) => setNewCamId(e.target.value ? Number(e.target.value) : null)}>
            {cams.map((c) => (
              <SelectItem key={c.id} value={String(c.id)} text={c.name} />
            ))}
          </Select>
        </div>
        <Button data-testid="gate-add" disabled={newCamId == null} onClick={addGate}>
          {t('gates.add')}
        </Button>
      </div>

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : (
        <>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  {headers.map((h) => (
                    <TableHeader key={h}>{t(h)}</TableHeader>
                  ))}
                  <TableHeader>{''}</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {zones.map((z) => (
                  <TableRow key={z.id} data-testid={`gate-row-${z.id}`}>
                    <TableCell>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontWeight: 600 }}>{camName(z.camera_id)}</span>
                        <span style={{ fontSize: 11, color: '#8d8d8d' }}>{z.name}</span>
                        {conflicted.has(z.camera_id) && <Tag type="red" size="sm">{t('gates.conflict')}</Tag>}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Select
                        id={`gate-dir-${z.id}`}
                        labelText=""
                        hideLabel
                        value={z.direction ?? 'entry'}
                        onChange={(e) => patch(z, { direction: e.target.value as 'entry' | 'exit' })}
                      >
                        <SelectItem value="entry" text={t('gates.dir.entry')} />
                        <SelectItem value="exit" text={t('gates.dir.exit')} />
                      </Select>
                    </TableCell>
                    <TableCell>
                      <Toggle
                        id={`gate-snap-${z.id}`}
                        labelText={t('gates.col.snapshot')}
                        hideLabel
                        size="sm"
                        toggled={z.snapshot}
                        onToggle={(v) => patch(z, { snapshot: v })}
                      />
                    </TableCell>
                    <TableCell>
                      <Toggle
                        id={`gate-on-${z.id}`}
                        labelText={t('gates.col.active')}
                        hideLabel
                        size="sm"
                        toggled={z.active}
                        onToggle={(v) => patch(z, { active: v })}
                      />
                    </TableCell>
                    <TableCell>
                      <Button kind="ghost" size="sm" data-testid={`gate-draw-${z.id}`} onClick={() => navigate('/config/zones')}>
                        {t('gates.drawEditor')}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {zones.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={headers.length + 1}>{t('gates.empty')}</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
          {conflicted.size > 0 && (
            <p data-testid="gate-conflict-msg" style={{ color: '#fa4d56', fontSize: 12, marginTop: 10 }}>
              {t('gates.conflictMsg')}
            </p>
          )}
        </>
      )}
    </div>
  )
}
