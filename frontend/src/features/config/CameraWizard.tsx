import { useEffect, useRef, useState } from 'react'
import {
  ComposedModal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Button,
  TextInput,
  Select,
  SelectItem,
  InlineLoading,
  InlineNotification,
} from '@carbon/react'
import { useT } from '../../app/i18n'
import {
  createCamera,
  updateCamera,
  listNodes,
  probeCamera,
  scanCamera,
  type Camera,
  type CameraNode,
  type ProbeResult,
  type ScanChannel,
} from '../../api/cameras'
import type { CredentialProfile } from '../../api/credentialProfiles'
import NewCredentialForm from './NewCredentialForm'

type Props = {
  camera?: Camera
  profiles: CredentialProfile[]
  locations: string[]
  onProfilesChanged: () => void
  onClose: () => void
  onSaved: () => void
}

const NEW_CREDENTIAL = 'new'

function safePath(value: string | null | undefined): string | null {
  if (!value) return null
  const raw = value.trim()
  if (!raw) return null
  if (raw.includes('://')) {
    try {
      const parsed = new URL(raw)
      return `${parsed.pathname}${parsed.search}`
    } catch {
      return null
    }
  }
  return raw.startsWith('/') ? raw : `/${raw}`
}

function streamText(s: { res: string; fps: number; codec: string } | null, path: string | null, failMsg: string) {
  return s ? `${s.res} · ${s.fps}fps · ${s.codec} (${path ?? '?'})` : failMsg
}

function channelLabel(ch: ScanChannel, failMsg: string): string {
  const main = ch.main ? `MAIN ${ch.main.res} · ${ch.main.codec}` : `MAIN ${failMsg}`
  const sub = ch.sub ? `SUB ${ch.sub.res} · ${ch.sub.codec}` : `SUB ${failMsg}`
  return `ch ${ch.channel} — ${main} / ${sub}`
}

function savedProbe(camera?: Camera): ProbeResult | null {
  if (!camera || (!camera.probe_main && !camera.probe_sub)) return null
  return {
    main: camera.probe_main,
    sub: camera.probe_sub,
    main_path: camera.main_path ?? safePath(camera.rtsp_main),
    sub_path: camera.sub_path ?? safePath(camera.rtsp_sub),
  }
}

export default function CameraWizard({ camera, profiles, locations, onProfilesChanged, onClose, onSaved }: Props) {
  const { t } = useT()
  const isEdit = camera != null
  const [nodes, setNodes] = useState<CameraNode[]>([])
  const [name, setName] = useState(camera?.name ?? '')
  const [location, setLocation] = useState(camera?.location ?? '')
  const [host, setHost] = useState(camera?.host ?? '')
  const [nodeId, setNodeId] = useState<number | ''>(camera?.node_id ?? '')
  const [mainPath, setMainPath] = useState(camera?.main_path ?? safePath(camera?.rtsp_main) ?? '')
  const [subPath, setSubPath] = useState(camera?.sub_path ?? safePath(camera?.rtsp_sub) ?? '')
  const [credentialId, setCredentialId] = useState<number | null>(camera?.credential_override_id ?? null)
  const [created, setCreated] = useState<CredentialProfile | null>(null)
  const [newCredential, setNewCredential] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scans, setScans] = useState<ScanChannel[]>([])
  const [scanSelected, setScanSelected] = useState<ScanChannel | null>(null)
  const [scanEmpty, setScanEmpty] = useState(false)
  const [connectionTouched, setConnectionTouched] = useState(false)
  const [probing, setProbing] = useState(false)
  const [probe, setProbe] = useState<ProbeResult | null>(() => savedProbe(camera))
  const [probeFailed, setProbeFailed] = useState(false)
  const [unverifiedAck, setUnverifiedAck] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const probeSeq = useRef(0)

  useEffect(() => {
    listNodes()
      .then((ns) => {
        setNodes(ns)
        if (!isEdit && ns.length > 0) setNodeId(ns[0].id)
      })
      .catch(() => {})
  }, [isEdit])

  const found = (probe?.main ? 1 : 0) + (probe?.sub ? 1 : 0)
  const needsProbe = !isEdit || connectionTouched
  const verified = !needsProbe || found >= 1
  const endpointHost = host.trim()
  const canSave = name.trim() !== '' && endpointHost !== '' && mainPath.trim() !== '' && !saving
  const subSameAsMain = safePath(subPath) != null && safePath(subPath) === safePath(mainPath)
  // profil nonaktif hanya tampil bila masih terpasang di kamera ini
  const profileOptions = [
    ...profiles.filter((p) => p.enabled || p.id === credentialId),
    ...(created && !profiles.some((p) => p.id === created.id) ? [created] : []),
  ]

  const clearProbe = () => {
    probeSeq.current += 1
    setProbing(false)
    setProbe(null)
    setProbeFailed(false)
    setUnverifiedAck(false)
    setConnectionTouched(true)
  }

  const invalidate = () => {
    clearProbe()
    setScanSelected(null)
    setScans([])
    setScanEmpty(false)
  }

  const runScan = async () => {
    if (!endpointHost) return
    invalidate()
    const seq = ++probeSeq.current
    setScanning(true)
    setError(null)
    try {
      const { streams } = await scanCamera(endpointHost)
      if (seq !== probeSeq.current) return
      setScans(streams)
      setScanEmpty(streams.length === 0)
      const first = streams[0]
      if (first && !isEdit) selectScan(first)
    } catch {
      if (seq === probeSeq.current) setScanEmpty(true)
    } finally {
      if (seq === probeSeq.current) setScanning(false)
    }
  }

  function selectScan(ch: ScanChannel) {
    setScanSelected(ch)
    setMainPath(ch.main_path ?? '')
    setSubPath(ch.sub_path ?? '')
    setProbe({ main: ch.main, sub: ch.sub, main_path: ch.main_path, sub_path: ch.sub_path })
    setProbeFailed(false)
    setConnectionTouched(true)
  }

  const runProbe = async () => {
    if (!endpointHost || !mainPath.trim()) return
    const seq = ++probeSeq.current
    setProbing(true)
    setProbe(null)
    setProbeFailed(false)
    setError(null)
    try {
      const result = await probeCamera({
        host: endpointHost,
        main_path: safePath(mainPath),
        sub_path: safePath(subPath),
        ...(credentialId != null ? { credential_override_id: credentialId } : {}),
        snapshot: true,
      })
      if (seq !== probeSeq.current) return
      setProbe(result)
      setMainPath(safePath(result.main_path) ?? mainPath)
      setSubPath(safePath(result.sub_path) ?? subPath)
    } catch {
      if (seq === probeSeq.current) setProbeFailed(true)
    } finally {
      if (seq === probeSeq.current) setProbing(false)
    }
  }

  const save = async () => {
    if (!verified && !unverifiedAck) {
      setUnverifiedAck(true) // klik kedua = simpan tanpa tes
      return
    }
    setSaving(true)
    setError(null)
    const connection = {
      host: endpointHost,
      node_id: nodeId === '' ? null : nodeId,
      rtsp_main: probe?.main_path ?? (safePath(mainPath) || null),
      rtsp_sub: probe?.sub_path ?? (safePath(subPath) || null),
      credential_override_id: credentialId,
    }
    const probeMeta = {
      probe_main: probe?.main ?? null,
      probe_sub: probe?.sub ?? null,
      status: probe?.main || probe?.sub ? 'online' : 'offline',
    }
    try {
      if (camera) {
        await updateCamera(
          camera.id,
          connectionTouched
            ? { name: name.trim(), location: location.trim() || null, ...connection, ...probeMeta }
            : { name: name.trim(), location: location.trim() || null },
        )
      } else {
        await createCamera({ name: name.trim(), location: location.trim() || null, ...connection, ...probeMeta })
      }
      onSaved()
    } catch (e) {
      setError(
        e instanceof Error && e.message === 'duplicate'
          ? t('cameras.wizard.duplicate')
          : t('cameras.saveError'),
      )
      setSaving(false)
    }
  }

  return (
    <ComposedModal open onClose={onClose} size="sm" preventCloseOnClickOutside>
      <ModalHeader title={t(isEdit ? 'cameras.wizard.editTitle' : 'cameras.wizard.title')} closeModal={onClose} />
      <ModalBody>
        <TextInput
          id="wiz-name"
          labelText={t('cameras.wizard.name')}
          placeholder="Lorong Manager"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <TextInput
          id="wiz-location"
          labelText={t('cameras.wizard.location')}
          placeholder="LT 2"
          list="wiz-locations"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          style={{ marginTop: 12 }}
        />
        <datalist id="wiz-locations">
          {locations.map((l) => <option key={l} value={l} />)}
        </datalist>
        <TextInput
          id="wiz-host"
          labelText={t('cameras.wizard.host')}
          helperText={t('cameras.wizard.hostHint')}
          placeholder="192.168.1.108"
          value={host}
          style={{ marginTop: 12 }}
          onChange={(e) => {
            setHost(e.target.value)
            invalidate()
          }}
        />
        <TextInput
          id="wiz-main-path"
          labelText={t('cameras.wizard.mainPath')}
          placeholder="/Streaming/Channels/101"
          value={mainPath}
          style={{ marginTop: 12 }}
          onChange={(e) => {
            setMainPath(e.target.value)
            clearProbe()
          }}
        />
        <TextInput
          id="wiz-sub-path"
          labelText={t('cameras.wizard.subPath')}
          helperText={t('cameras.wizard.subHint')}
          placeholder="/Streaming/Channels/102"
          value={subPath}
          style={{ marginTop: 12 }}
          onChange={(e) => {
            setSubPath(e.target.value)
            clearProbe()
          }}
        />
        {subSameAsMain && (
          <InlineNotification
            kind="warning"
            lowContrast
            hideCloseButton
            title={t('cameras.wizard.subSameAsMain')}
            style={{ marginTop: 8 }}
          />
        )}
        <Select
          id="wiz-credential"
          labelText={t('cameras.wizard.credential')}
          value={credentialId ?? ''}
          style={{ marginTop: 12 }}
          onChange={(e) => {
            if (e.target.value === NEW_CREDENTIAL) {
              setNewCredential(true)
              return
            }
            setCredentialId(e.target.value === '' ? null : Number(e.target.value))
            clearProbe()
          }}
        >
          <SelectItem value="" text={t('cameras.wizard.credentialDefault')} />
          {profileOptions.map((p) => <SelectItem key={p.id} value={p.id} text={p.name} />)}
          <SelectItem value={NEW_CREDENTIAL} text={t('cameras.wizard.credentialNew')} />
        </Select>
        {newCredential && (
          <NewCredentialForm
            onCancel={() => setNewCredential(false)}
            onCreated={(p) => {
              setNewCredential(false)
              setCreated(p)
              setCredentialId(p.id)
              clearProbe()
              onProfilesChanged()
            }}
          />
        )}

        <Button
          kind="secondary"
          size="sm"
          onClick={runProbe}
          disabled={probing || !endpointHost || !mainPath.trim()}
          style={{ marginTop: 12 }}
        >
          {t('cameras.wizard.probe')}
        </Button>
        <div
          data-testid="probe-box"
          style={{ border: '1px dashed var(--cds-border-subtle)', padding: 12, marginTop: 12, fontSize: 12, minHeight: 84 }}
        >
          {probing ? (
            <InlineLoading description={t('cameras.wizard.probing')} />
          ) : probe || probeFailed ? (
            <>
              <div style={{ color: probe?.main ? '#42be65' : '#fa4d56' }}>
                MAIN: {streamText(probe?.main ?? null, probe?.main_path ?? null, t('cameras.wizard.probeFail'))}
              </div>
              <div style={{ color: probe?.sub ? '#42be65' : '#fa4d56' }}>
                SUB: {streamText(probe?.sub ?? null, probe?.sub_path ?? null, t('cameras.wizard.probeFail'))}
              </div>
              {probe?.snapshot_jpeg_b64 && (
                <img
                  data-testid="probe-thumb"
                  alt=""
                  src={`data:image/jpeg;base64,${probe.snapshot_jpeg_b64}`}
                  style={{ display: 'block', width: '100%', maxWidth: 320, marginTop: 8 }}
                />
              )}
            </>
          ) : (
            t('cameras.wizard.probeHint')
          )}
        </div>

        <details data-testid="wiz-advanced" style={{ marginTop: 14 }}>
          <summary style={{ cursor: 'pointer', fontSize: 13 }}>{t('cameras.wizard.advanced')}</summary>
          {nodes.length > 1 && (
            <Select
              id="wiz-node"
              labelText={t('cameras.wizard.node')}
              value={nodeId}
              style={{ marginTop: 12 }}
              onChange={(e) => {
                setNodeId(Number(e.target.value))
                if (isEdit) clearProbe()
              }}
            >
              {nodes.map((n) => <SelectItem key={n.id} value={n.id} text={n.name} />)}
            </Select>
          )}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12 }}>
            <Button kind="secondary" size="sm" onClick={runScan} disabled={scanning || !endpointHost}>
              {t('cameras.wizard.autoDetect')}
            </Button>
            {scans.length > 0 && !scanning && (
              <span style={{ fontSize: 12, color: 'var(--cds-text-secondary)' }}>
                {scans.length} {t('cameras.wizard.scanFound')}
              </span>
            )}
          </div>
          {scanning && <InlineLoading style={{ marginTop: 8 }} description={t('cameras.wizard.scanning')} />}
          {scanEmpty && !scanning && (
            <p style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginTop: 8 }}>
              {t('cameras.wizard.scanEmpty')}
            </p>
          )}
          {scans.length > 0 && !scanning && (
            <Select
              id="wiz-scan"
              labelText={t('cameras.wizard.detectedPaths')}
              value={scanSelected?.channel ?? ''}
              onChange={(e) => {
                const ch = scans.find((s) => s.channel === Number(e.target.value))
                if (ch) selectScan(ch)
              }}
              style={{ marginTop: 12 }}
            >
              <SelectItem value="" text={t('cameras.wizard.chooseChannel')} />
              {scans.map((ch) => (
                <SelectItem key={ch.channel} value={ch.channel} text={channelLabel(ch, t('cameras.wizard.probeFail'))} />
              ))}
            </Select>
          )}
        </details>

        {unverifiedAck && !verified && (
          <InlineNotification
            kind="warning"
            lowContrast
            hideCloseButton
            title={t('cameras.wizard.unverified')}
            style={{ marginTop: 12 }}
          />
        )}
        {error && (
          <InlineNotification
            kind="error"
            lowContrast
            subtitle={error}
            title={t('cameras.wizard.saveFailed')}
            onCloseButtonClick={() => setError(null)}
            style={{ marginTop: 12 }}
          />
        )}
      </ModalBody>
      <ModalFooter>
        <Button kind="ghost" onClick={onClose}>{t('common.cancel')}</Button>
        <Button onClick={save} disabled={!canSave}>{t('common.save')}</Button>
      </ModalFooter>
    </ComposedModal>
  )
}
