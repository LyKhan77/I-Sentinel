import { useEffect, useState } from 'react'
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
  listNodes,
  probeCamera,
  type CameraNode,
  type ProbeResult,
} from '../../api/cameras'

type Props = { onClose: () => void; onSaved: () => void }

function streamText(s: { res: string; fps: number; codec: string } | null, path: string | null, failMsg: string) {
  return s ? `${s.res} · ${s.fps}fps · ${s.codec} (${path ?? '?'})` : failMsg
}

export default function CameraWizard({ onClose, onSaved }: Props) {
  const { t } = useT()
  const [nodes, setNodes] = useState<CameraNode[]>([])
  const [name, setName] = useState('')
  const [location, setLocation] = useState('')
  const [host, setHost] = useState('')
  const [nodeId, setNodeId] = useState<number | ''>('')
  const [probing, setProbing] = useState(false)
  const [probe, setProbe] = useState<ProbeResult | null>(null)
  const [probeFailed, setProbeFailed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listNodes()
      .then((ns) => {
        setNodes(ns)
        if (ns.length > 0) setNodeId(ns[0].id)
      })
      .catch(() => {})
  }, [])

  const found = (probe?.main ? 1 : 0) + (probe?.sub ? 1 : 0)
  const canSave = name.trim() !== '' && host.trim() !== '' && found >= 1

  const runProbe = async () => {
    if (host.trim() === '') return
    setProbing(true)
    setProbe(null)
    setProbeFailed(false)
    setError(null)
    try {
      setProbe(await probeCamera(host.trim()))
    } catch {
      setProbeFailed(true)
    } finally {
      setProbing(false)
    }
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await createCamera({
        name: name.trim(),
        location: location.trim() || null,
        host: host.trim(),
        node_id: nodeId === '' ? null : nodeId,
        rtsp_main: probe?.main_path ?? null,
        rtsp_sub: probe?.sub_path ?? null,
      })
      onSaved()
    } catch (e) {
      setError(e instanceof Error && e.message === 'duplicate' ? t('cameras.wizard.duplicate') : t('cameras.saveError'))
      setSaving(false)
    }
  }

  return (
    <ComposedModal open onClose={onClose} size="sm" preventCloseOnClickOutside>
      <ModalHeader title={t('cameras.wizard.title')} closeModal={onClose} />
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
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
          <TextInput
            id="wiz-host"
            labelText={t('cameras.wizard.host')}
            placeholder="192.168.1.108"
            value={host}
            onChange={(e) => {
              setHost(e.target.value)
              setProbe(null)
              setProbeFailed(false)
            }}
          />
          <Select
            id="wiz-node"
            labelText={t('cameras.wizard.node')}
            value={nodeId}
            onChange={(e) => setNodeId(Number(e.target.value))}
          >
            {nodes.map((n) => (
              <SelectItem key={n.id} value={n.id} text={n.name} />
            ))}
          </Select>
        </div>

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
        <Button kind="ghost" onClick={onClose}>
          {t('common.cancel')}
        </Button>
        <Button kind="secondary" onClick={runProbe} disabled={probing || host.trim() === ''}>
          {t('cameras.wizard.probe')}
        </Button>
        <Button onClick={save} disabled={!canSave || saving}>
          {t('common.save')}
        </Button>
      </ModalFooter>
    </ComposedModal>
  )
}
