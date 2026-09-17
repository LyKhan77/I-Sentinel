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
} from '@carbon/react'
import { useT } from '../../app/i18n'
import {
  createCamera,
  updateCamera,
  listNodes,
  probeCamera,
  type Camera,
  type CameraNode,
  type ProbeResult,
} from '../../api/cameras'
import type { StreamSource } from '../../api/streamSources'
import type { LocationGroup } from '../../api/locationGroups'
import type { CredentialProfile } from '../../api/credentialProfiles'
import LocationGroupSelect from './LocationGroupSelect'

type Props = {
  camera?: Camera
  sources?: StreamSource[]
  groups?: LocationGroup[]
  profiles?: CredentialProfile[]
  onClose: () => void
  onSaved: () => void
}

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

function savedProbe(camera?: Camera): ProbeResult | null {
  if (!camera || (!camera.probe_main && !camera.probe_sub)) return null
  return {
    main: camera.probe_main,
    sub: camera.probe_sub,
    main_path: camera.source_id != null ? (camera.main_path ?? safePath(camera.rtsp_main)) : camera.rtsp_main,
    sub_path: camera.source_id != null ? (camera.sub_path ?? safePath(camera.rtsp_sub)) : camera.rtsp_sub,
  }
}

export default function CameraWizard({ camera, sources = [], groups = [], profiles = [], onClose, onSaved }: Props) {
  const { t } = useT()
  const isEdit = camera != null
  const [nodes, setNodes] = useState<CameraNode[]>([])
  const [name, setName] = useState(camera?.name ?? '')
  const [location, setLocation] = useState(camera?.location ?? '')
  const [host, setHost] = useState(camera?.host ?? '')
  const [nodeId, setNodeId] = useState<number | ''>(camera?.node_id ?? '')
  const [sourceId, setSourceId] = useState<number | ''>(camera?.source_id ?? '')
  const [groupId, setGroupId] = useState<number | ''>(camera?.location_group_id ?? '')
  const [credentialId, setCredentialId] = useState<number | ''>(camera?.credential_override_id ?? '')
  const [mainPath, setMainPath] = useState(camera?.main_path ?? safePath(camera?.rtsp_main) ?? '')
  const [subPath, setSubPath] = useState(camera?.sub_path ?? safePath(camera?.rtsp_sub) ?? '')
  const [pathsTouched, setPathsTouched] = useState(false)
  const [connectionTouched, setConnectionTouched] = useState(false)
  const [probing, setProbing] = useState(false)
  const [probe, setProbe] = useState<ProbeResult | null>(() => savedProbe(camera))
  const [probeFailed, setProbeFailed] = useState(false)
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

  const sourceMode = sourceId !== ''
  const found = (probe?.main ? 1 : 0) + (probe?.sub ? 1 : 0)
  const needsProbe = !isEdit || connectionTouched
  const endpointReady = sourceMode ? mainPath.trim() !== '' : host.trim() !== ''
  const canSave = name.trim() !== '' && endpointReady && (!needsProbe || found >= 1)

  const clearProbe = () => {
    probeSeq.current += 1
    setProbing(false)
    setProbe(null)
    setProbeFailed(false)
    setConnectionTouched(true)
  }

  const runProbe = async () => {
    if (!endpointReady) return
    const seq = ++probeSeq.current
    setProbing(true)
    setProbe(null)
    setProbeFailed(false)
    setError(null)
    try {
      const result = sourceMode
        ? await probeCamera({
            source_id: sourceId as number,
            credential_override_id: credentialId === '' ? undefined : credentialId,
            main_path: safePath(mainPath),
            sub_path: safePath(subPath),
          })
        : pathsTouched
          ? await probeCamera({
              host: host.trim(),
              main_path: safePath(mainPath),
              sub_path: safePath(subPath),
            })
          : await probeCamera(host.trim())
      if (seq !== probeSeq.current) return
      setProbe(result)
      if (sourceMode || pathsTouched) {
        setMainPath(safePath(result.main_path) ?? '')
        setSubPath(safePath(result.sub_path) ?? '')
      }
    } catch {
      if (seq === probeSeq.current) setProbeFailed(true)
    } finally {
      if (seq === probeSeq.current) setProbing(false)
    }
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    const connection = sourceMode
      ? {
          source_id: sourceId as number,
          location_group_id: groupId === '' ? null : groupId,
          credential_override_id: credentialId === '' ? null : credentialId,
          node_id: nodeId === '' ? null : nodeId,
          main_path: safePath(probe?.main_path) ?? safePath(mainPath),
          sub_path: safePath(probe?.sub_path) ?? safePath(subPath),
        }
      : {
          host: host.trim(),
          node_id: nodeId === '' ? null : nodeId,
          rtsp_main: probe?.main_path ?? (safePath(mainPath) || null),
          rtsp_sub: probe?.sub_path ?? (safePath(subPath) || null),
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
        await createCamera({
          name: name.trim(),
          location: location.trim() || null,
          ...connection,
          ...probeMeta,
        })
      }
      onSaved()
    } catch (e) {
      setError(e instanceof Error && e.message === 'duplicate' ? t('cameras.wizard.duplicate') : t('cameras.saveError'))
      setSaving(false)
    }
  }

  const selectedSource = sources.find((source) => source.id === sourceId)
  return (
    <ComposedModal open onClose={onClose} size="sm" preventCloseOnClickOutside>
      <ModalHeader title={t(isEdit ? 'cameras.wizard.editTitle' : 'cameras.wizard.title')} closeModal={onClose} />
      <ModalBody>
        <TextInput
          id="wiz-name"
          labelText={t('cameras.wizard.name')}
          placeholder="CAM-06 · Kantor Lobi"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <TextInput
          id="wiz-location"
          labelText={t('cameras.wizard.location')}
          placeholder="Gedung Kantor Lt.1"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          style={{ marginTop: 12 }}
        />
        <div style={{ display: 'grid', gap: 12, marginTop: 12 }}>
          <Select
            id="wiz-source"
            labelText={t('cameras.wizard.source')}
            value={sourceId}
            onChange={(e) => {
              const next = e.target.value === '' ? '' : Number(e.target.value)
              setSourceId(next)
              const source = sources.find((item) => item.id === next)
              if (source) setHost(source.port === 554 ? source.host : `${source.host}:${source.port}`)
              clearProbe()
            }}
          >
            <SelectItem value="" text={t('cameras.wizard.legacySource')} />
            {sources
              .filter((source) => source.enabled || source.id === sourceId)
              .map((source) => <SelectItem key={source.id} value={source.id} text={`${source.name} · ${source.host}:${source.port}`} />)}
          </Select>
          <LocationGroupSelect
            groups={groups}
            value={groupId}
            onChange={setGroupId}
            emptyLabel={t('cameras.wizard.noGroup')}
            labelText={t('cameras.wizard.group')}
          />
          {sourceMode && (
            <Select
              id="wiz-credential"
              labelText={t('cameras.wizard.credential')}
              value={credentialId}
              onChange={(e) => {
                setCredentialId(e.target.value === '' ? '' : Number(e.target.value))
                clearProbe()
              }}
            >
              <SelectItem value="" text={t('cameras.wizard.sourceDefault')} />
              {profiles
                .filter((profile) => profile.enabled || profile.id === credentialId)
                .map((profile) => <SelectItem key={profile.id} value={profile.id} text={`${profile.name} · ${profile.username}`} />)}
            </Select>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
          <TextInput
            id="wiz-host"
            labelText={t('cameras.wizard.host')}
            placeholder="192.168.1.108"
            value={host}
            disabled={sourceMode}
            onChange={(e) => {
              setHost(e.target.value)
              clearProbe()
            }}
          />
          <Select
            id="wiz-node"
            labelText={t('cameras.wizard.node')}
            value={nodeId}
            onChange={(e) => {
              setNodeId(Number(e.target.value))
              if (isEdit) clearProbe()
            }}
          >
            {nodes.map((n) => <SelectItem key={n.id} value={n.id} text={n.name} />)}
          </Select>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
          <TextInput
            id="wiz-main-path"
            labelText={t('cameras.wizard.mainPath')}
            placeholder="/Streaming/Channels/101"
            value={mainPath}
            onChange={(e) => {
              setMainPath(e.target.value)
              setPathsTouched(true)
              clearProbe()
            }}
          />
          <TextInput
            id="wiz-sub-path"
            labelText={t('cameras.wizard.subPath')}
            placeholder="/Streaming/Channels/102"
            value={subPath}
            onChange={(e) => {
              setSubPath(e.target.value)
              setPathsTouched(true)
              clearProbe()
            }}
          />
        </div>
        {selectedSource && <div style={{ color: 'var(--cds-text-secondary)', fontSize: 12, marginTop: 8 }}>{selectedSource.name}</div>}
        <div
          data-testid="probe-box"
          style={{ border: '1px dashed var(--cds-border-subtle)', padding: 12, marginTop: 14, fontSize: 12, minHeight: 84 }}
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
            </>
          ) : (
            t('cameras.wizard.probeHint')
          )}
        </div>
        {error && <div style={{ color: '#fa4d56', marginTop: 8 }}>{error}</div>}
      </ModalBody>
      <ModalFooter>
        <Button kind="ghost" onClick={onClose}>{t('common.cancel')}</Button>
        <Button kind="secondary" onClick={runProbe} disabled={probing || !endpointReady}>{t('cameras.wizard.probe')}</Button>
        <Button onClick={save} disabled={!canSave || saving}>{t('common.save')}</Button>
      </ModalFooter>
    </ComposedModal>
  )
}
