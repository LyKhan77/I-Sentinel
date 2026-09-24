import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react'
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
import { useT, type TKey } from '../../app/i18n'
import { getMe, type Me } from '../../api/client'
import {
  listCameras,
  updateCamera,
  deleteCamera,
  probeCamera,
  importCameras,
  syncGo2rtc,
  type Camera,
  type CameraImportEntry,
  type CameraImportItem,
  type CameraImportResult,
} from '../../api/cameras'
import { listStreamSources, type StreamSource } from '../../api/streamSources'
import { listCredentialProfiles, type CredentialProfile } from '../../api/credentialProfiles'
import CameraSourcesPanel from './CameraSourcesPanel'
import CameraWizard from './CameraWizard'

// status dot: probe_main ada → online; probe pernah gagal → offline; belum pernah → unknown
function statusKind(cam: Camera): 'online' | 'offline' | 'unknown' {
  if (cam.probe_main) return 'online'
  if (cam.status === 'offline') return 'offline'
  return 'unknown'
}

const DOT_COLOR = { online: '#42be65', offline: '#fa4d56', unknown: '#8d8d8d' } as const

const IMPORT_CLASS_LABEL: Record<CameraImportItem['classification'], TKey> = {
  MATCHED: 'cameras.import.class.matched',
  CREATE: 'cameras.import.class.create',
  UPDATE: 'cameras.import.class.update',
  'NEW SOURCE': 'cameras.import.class.newSource',
  ORPHAN: 'cameras.import.class.orphan',
  DUPLICATE: 'cameras.import.class.duplicate',
  CREDENTIAL: 'cameras.import.class.credential',
}

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

function parseCctvList(text: string): CameraImportEntry[] {
  const entries: CameraImportEntry[] = []
  for (const [index, rawLine] of text.split(/\r?\n/).entries()) {
    const line = rawLine.trim()
    if (!line) continue
    const match = line.match(/^rtsp:\/\/([^/]+)(\/\S+)\s+\((.*)\)$/)
    if (!match) throw new Error(String(index + 1))
    const [, host, rtspMain, location] = match
    const rtspSub = rtspMain.replace(/01(?=$|\?)/, '02')
    if (rtspSub === rtspMain) throw new Error(String(index + 1))
    entries.push({
      name: `NVR-CAM-${String(entries.length + 1).padStart(2, '0')}`,
      location: location.trim() || null,
      host,
      rtsp_main: rtspMain,
      rtsp_sub: rtspSub,
    })
  }
  if (entries.length === 0) throw new Error('0')
  return entries
}

export default function CamerasPage() {
  const { t } = useT()
  const [cams, setCams] = useState<Camera[]>([])
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [editing, setEditing] = useState<Camera | null>(null)
  const [probingId, setProbingId] = useState<number | null>(null)
  const [toDelete, setToDelete] = useState<Camera | null>(null)
  const [sources, setSources] = useState<StreamSource[]>([])
  const [profiles, setProfiles] = useState<CredentialProfile[]>([])
  const importInput = useRef<HTMLInputElement>(null)
  const [importEntries, setImportEntries] = useState<CameraImportEntry[] | null>(null)
  const [importPlan, setImportPlan] = useState<CameraImportResult | null>(null)
  const isAdmin = me?.role === 'admin'
  const [importBusy, setImportBusy] = useState(false)
  const [syncBusy, setSyncBusy] = useState(false)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)
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

  const syncStreams = async () => {
    setSyncBusy(true)
    setSyncMsg(null)
    try {
      const r = await syncGo2rtc()
      setSyncMsg(
        t('cameras.sync.done')
          .replace('{added}', String(r.added.length))
          .replace('{removed}', String(r.removed.length)),
      )
      await refresh()
    } catch {
      setError(t('cameras.sync.error'))
    } finally {
      setSyncBusy(false)
    }
  }

  const refreshReferences = useCallback(async () => {
    try {
      const [nextSources, nextProfiles] = await Promise.all([
        listStreamSources(),
        listCredentialProfiles(),
      ])
      setSources(nextSources)
      setProfiles(nextProfiles)
    } catch {
      setError(t('cameras.sources.loadError'))
    }
  }, [t])

  useEffect(() => {
    getMe()
      .then((user) => {
        setMe(user)
        if (user?.role === 'admin') void refreshReferences()
      })
      .catch(() => setMe(null))
    refresh()
  }, [refresh, refreshReferences])

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

  const closeImport = () => {
    setImportPlan(null)
    setImportEntries(null)
  }

  const previewImport = async (file: File) => {
    setImportBusy(true)
    setError(null)
    try {
      const entries = parseCctvList(await file.text())
      setImportEntries(entries)
      setImportPlan(await importCameras(entries))
    } catch (e) {
      const detail = e instanceof Error ? e.message : ''
      setError(
        /^\d+$/.test(detail)
          ? detail === '0'
            ? t('cameras.import.empty')
            : t('cameras.import.invalidLine').replace('{line}', detail)
          : t('cameras.import.loadError'),
      )
    } finally {
      setImportBusy(false)
    }
  }

  const onImportFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file) void previewImport(file)
  }

  const applyImport = async () => {
    if (!importEntries || !importPlan || importPlan.errors.length > 0 || importPlan.unmatched.length > 0) return
    setImportBusy(true)
    setError(null)
    try {
      const result = await importCameras(importEntries, true)
      if (result.applied) {
        closeImport()
        await refresh()
      } else {
        setImportPlan(result)
      }
    } catch {
      setError(t('cameras.import.applyError'))
    } finally {
      setImportBusy(false)
    }
  }

  const headers = [
    { key: 'name', header: t('cameras.col.name') },
    { key: 'location', header: t('cameras.col.location') },
    { key: 'streams', header: t('cameras.col.streams') },
    { key: 'node', header: t('cameras.col.node') },
    { key: 'status', header: t('cameras.col.status') },
    { key: 'actions', header: '' },
  ]

  return (
    <>
      {isAdmin && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 14 }}>
          <input
            ref={importInput}
            type="file"
            accept=".txt,text/plain"
            data-testid="camera-import-input"
            style={{ display: 'none' }}
            onChange={onImportFile}
          />
          <Button kind="ghost" disabled={importBusy} data-testid="camera-import-btn" onClick={() => importInput.current?.click()}>
            {t('cameras.import.button')}
          </Button>
          <Button
            kind="ghost"
            disabled={syncBusy}
            data-testid="go2rtc-sync"
            onClick={syncStreams}
            title={t('cameras.sync.hint')}
          >
            {t('cameras.sync.btn')}
          </Button>
          <Button onClick={() => setWizardOpen(true)}>{t('cameras.add')}</Button>
        </div>
      )}
      {isAdmin && (
        <CameraSourcesPanel
          sources={sources}
          profiles={profiles}
          onChanged={refreshReferences}
        />
      )}

      {error && (
        <InlineNotification
          kind="error"
          lowContrast
          title={t('common.error')}
          subtitle={error}
          onCloseButtonClick={() => setError(null)}
        />
      )}

      {syncMsg && (
        <InlineNotification
          kind="success"
          lowContrast
          title={t('cameras.sync.btn')}
          subtitle={syncMsg}
          data-testid="go2rtc-sync-result"
          onCloseButtonClick={() => setSyncMsg(null)}
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
                          {cam.source && <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)' }}>{cam.source.name}</div>}
                        </TableCell>
                        <TableCell>{cam.location ?? '—'}</TableCell>
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
                            <Button kind="ghost" size="sm" disabled={!isAdmin} onClick={() => setEditing(cam)}>
                              {t('cameras.edit')}
                            </Button>
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

      {(wizardOpen || editing) && (
        <CameraWizard
          camera={editing ?? undefined}
          profiles={profiles}
          locations={[...new Set(cams.map((c) => c.location).filter((l): l is string => !!l))].sort()}
          onProfilesChanged={() => void refreshReferences()}
          onClose={() => {
            setWizardOpen(false)
            setEditing(null)
          }}
          onSaved={() => {
            setWizardOpen(false)
            setEditing(null)
            void refresh()
          }}
        />
      )}

      <Modal
        open={importPlan != null}
        modalHeading={t('cameras.import.title')}
        primaryButtonText={importBusy ? t('common.loading') : t('cameras.import.apply')}
        secondaryButtonText={t('common.cancel')}
        primaryButtonDisabled={
          importBusy || importPlan == null || importPlan.errors.length > 0 || importPlan.unmatched.length > 0
        }
        onRequestClose={closeImport}
        onRequestSubmit={applyImport}
        size="lg"
      >
        {importPlan && (
          <>
            <p>
              {t('cameras.import.summary')
                .replace('{total}', String(importPlan.total))
                .replace('{matched}', String(importPlan.matched))
                .replace('{updated}', String(importPlan.updated))}
            </p>
            {importPlan.errors.length > 0 && (
              <ul>
                {importPlan.errors.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
            {importPlan.items.length > 0 && (
              <ul data-testid="camera-import-classifications">
                {importPlan.items.map((item, index) => (
                  <li key={`${item.classification}-${item.camera_id ?? index}`}>
                    {t(IMPORT_CLASS_LABEL[item.classification])} · {item.after.name} · {item.after.host ?? item.after.source ?? ''}
                    {item.after.main_path ?? item.after.rtsp_main ?? ''}
                  </li>
                ))}
              </ul>
            )}
            {importPlan.unmatched.length > 0 && (
              <>
                <p>{t('cameras.import.unmatched')}</p>
                <ul>
                  {importPlan.unmatched.map((item) => (
                    <li key={`${item.after.host}${item.after.rtsp_main}`}>
                      {item.after.name} · {item.after.host}{item.after.rtsp_main}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </Modal>

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
    </>
  )
}
