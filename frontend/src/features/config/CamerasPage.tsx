import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  DataTable,
  InlineLoading,
  InlineNotification,
  Modal,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  Tag,
} from '@carbon/react'
import { useT } from '../../app/i18n'
import { getMe, type Me } from '../../api/client'
import {
  listCameras,
  updateCamera,
  deleteCamera,
  probeCamera,
  type Camera,
} from '../../api/cameras'
import CameraWizard from './CameraWizard'

// status dot: probe_main ada → online; probe pernah gagal → offline; belum pernah → unknown
function statusKind(cam: Camera): 'online' | 'offline' | 'unknown' {
  if (cam.probe_main) return 'online'
  if (cam.status === 'offline') return 'offline'
  return 'unknown'
}

const DOT_COLOR = { online: '#42be65', offline: '#fa4d56', unknown: '#8d8d8d' } as const

function StreamLine({ label, stream }: { label: string; stream: Camera['probe_main'] }) {
  const { t } = useT()
  return (
    <div style={{ fontSize: 12 }}>
      <span style={{ color: stream ? '#42be65' : '#fa4d56' }}>●</span>{' '}
      {label}{' '}
      {stream ? `${stream.res} · ${stream.fps}fps · ${stream.codec}` : t('cameras.streamFail')}
    </div>
  )
}

export default function CamerasPage() {
  const { t } = useT()
  const [cams, setCams] = useState<Camera[]>([])
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [probingId, setProbingId] = useState<number | null>(null)
  const [toDelete, setToDelete] = useState<Camera | null>(null)

  const isAdmin = me?.role === 'admin'

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setCams(await listCameras())
    } catch {
      setError(t('cameras.loadError'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null))
    refresh()
  }, [refresh])

  const reprobe = async (cam: Camera) => {
    setProbingId(cam.id)
    try {
      await probeCamera(cam.host, cam.id)
      await refresh()
    } catch {
      setError(t('cameras.probeError'))
    } finally {
      setProbingId(null)
    }
  }

  const toggleEnabled = async (cam: Camera) => {
    try {
      await updateCamera(cam.id, { enabled: !cam.enabled })
      await refresh()
    } catch {
      setError(t('cameras.saveError'))
    }
  }

  const doDelete = async () => {
    if (!toDelete) return
    try {
      await deleteCamera(toDelete.id)
      setToDelete(null)
      await refresh()
    } catch {
      setError(t('cameras.saveError'))
      setToDelete(null)
    }
  }

  const headers = [
    { key: 'name', header: t('cameras.col.name') },
    { key: 'streams', header: t('cameras.col.streams') },
    { key: 'node', header: t('cameras.col.node') },
    { key: 'status', header: t('cameras.col.status') },
    { key: 'actions', header: '' },
  ]

  return (
    <div style={{ padding: 32, maxWidth: 960 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h1 style={{ fontWeight: 300, margin: 0 }}>{t('cameras.title')}</h1>
        {isAdmin && <Button onClick={() => setWizardOpen(true)}>{t('cameras.add')}</Button>}
      </div>

      {error && (
        <InlineNotification
          kind="error"
          title={t('common.error')}
          subtitle={error}
          onCloseButtonClick={() => setError(null)}
        />
      )}

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : (
        <DataTable rows={[]} headers={headers}>
          {({ headers: cols }) => (
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    {cols.map((h) => (
                      <TableHeader key={h.key}>{h.header}</TableHeader>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {cams.map((cam) => {
                    const kind = statusKind(cam)
                    return (
                      <TableRow key={cam.id}>
                        <TableCell>
                          <div style={{ fontWeight: 600 }}>{cam.name}</div>
                          {cam.location && (
                            <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)' }}>{cam.location}</div>
                          )}
                        </TableCell>
                        <TableCell>
                          <StreamLine label="MAIN" stream={cam.probe_main} />
                          <StreamLine label="SUB" stream={cam.probe_sub} />
                        </TableCell>
                        <TableCell>{cam.node_id != null ? <Tag size="sm">node {cam.node_id}</Tag> : '—'}</TableCell>
                        <TableCell>
                          <span style={{ color: DOT_COLOR[kind] }}>●</span>{' '}
                          {t(`cameras.status.${kind}` as const)}
                        </TableCell>
                        <TableCell>
                          <div style={{ display: 'flex', gap: 4 }}>
                            <Button
                              kind="ghost"
                              size="sm"
                              disabled={!isAdmin || probingId === cam.id}
                              onClick={() => reprobe(cam)}
                            >
                              {probingId === cam.id ? <InlineLoading /> : t('cameras.probe')}
                            </Button>
                            <Button kind="ghost" size="sm" disabled={!isAdmin} onClick={() => toggleEnabled(cam)}>
                              {cam.enabled ? t('cameras.disable') : t('cameras.enable')}
                            </Button>
                            <Button
                              kind="danger--ghost"
                              size="sm"
                              disabled={!isAdmin}
                              onClick={() => setToDelete(cam)}
                            >
                              {t('cameras.delete')}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                  {cams.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5}>{t('cameras.empty')}</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </DataTable>
      )}

      {wizardOpen && (
        <CameraWizard
          onClose={() => setWizardOpen(false)}
          onSaved={() => {
            setWizardOpen(false)
            refresh()
          }}
        />
      )}

      <Modal
        open={toDelete != null}
        modalHeading={t('cameras.deleteConfirmTitle')}
        primaryButtonText={t('cameras.delete')}
        secondaryButtonText={t('common.cancel')}
        onRequestClose={() => setToDelete(null)}
        onRequestSubmit={doDelete}
        danger
        size="sm"
      >
        <p>{t('cameras.deleteConfirmBody').replace('{name}', toDelete?.name ?? '')}</p>
      </Modal>
    </div>
  )
}
