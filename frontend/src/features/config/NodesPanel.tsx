import { useCallback, useEffect, useState } from 'react'
import { Button, Select, InlineNotification, Tile } from '@carbon/react'
import { useT } from '../../app/i18n'
import { listNodes, setNodeDetectorDevice, setNodeFaceDevice, type CameraNode } from '../../api/cameras'

export default function NodesPanel() {
  const { t } = useT()
  const [nodes, setNodes] = useState<CameraNode[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  // pilihan sementara per node id sebelum disimpan (detector & face terpisah)
  const [draft, setDraft] = useState<Record<number, { detector: string; face: string }>>({})
  const [savedId, setSavedId] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      const rows = await listNodes()
      setNodes(rows)
    } catch {
      setError(true)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const save = async (node: CameraNode) => {
    const d = draft[node.id] ?? {}
    const device = d.detector ?? node.detector_device ?? ''
    const faceDevice = d.face ?? node.face_device ?? ''
    const tasks = []
    if (device !== (node.detector_device ?? ''))
      tasks.push(setNodeDetectorDevice(node.id, device))
    if (faceDevice !== (node.face_device ?? ''))
      tasks.push(setNodeFaceDevice(node.id, faceDevice))
    try {
      if (tasks.length) await Promise.all(tasks)
      setNodes((rows) =>
        rows.map((n) =>
          n.id === node.id ? { ...n, detector_device: device, face_device: faceDevice } : n,
        ),
      )
      setSavedId(node.id)
      setError(false)
    } catch {
      setError(true)
      setSavedId(null)
    }
  }

  if (loading) return <p style={{ color: '#8d8d8d' }}>{t('common.loading')}</p>

  return (
    <div>
      {error && (
        <InlineNotification
          kind="error"
          lowContrast
          title={t('common.error')}
          subtitle={t('nodes.saveError')}
          onCloseButtonClick={() => setError(false)}
        />
      )}
      {nodes.length === 0 ? (
        <p style={{ color: '#8d8d8d' }}>{t('nodes.empty')}</p>
      ) : (
        nodes.map((node) => {
          const gpus = node.hw?.gpus ?? []
          const value = draft[node.id]?.detector ?? node.detector_device ?? ''
          const faceValue = draft[node.id]?.face ?? node.face_device ?? ''
          return (
            <Tile key={node.id} style={{ background: '#262626', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: node.status === 'online' ? '#42be65' : '#fa4d56' }}>●</span>
                <span style={{ fontWeight: 600 }}>{node.name}</span>
                <span style={{ fontSize: 12, color: '#8d8d8d' }}>{node.type}</span>
              </div>
              <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', marginTop: 10, flexWrap: 'wrap' }}>
                <div style={{ minWidth: 260, flexGrow: 1, maxWidth: 480 }}>
                  <Select
                    id={`device-${node.id}`}
                    labelText={t('nodes.device')}
                    value={value}
                    onChange={(e) => setDraft((d) => ({ ...d, [node.id]: { ...(d[node.id] ?? { detector: value, face: faceValue }), detector: e.target.value } }))}
                  >
                    <option value="">{t('nodes.auto')}</option>
                    {gpus.map((g) => (
                      <option key={g.idx} value={`cuda:${g.idx}`}>
                        {`cuda:${g.idx}`} — {g.name}
                      </option>
                    ))}
                  </Select>
                  {gpus.length === 0 && (
                    <p style={{ fontSize: 12, color: '#8d8d8d', margin: '4px 0 0' }}>{t('nodes.noGpu')}</p>
                  )}
                </div>
                <div style={{ minWidth: 260, flexGrow: 1, maxWidth: 480 }}>
                  <Select
                    id={`face-device-${node.id}`}
                    labelText={t('nodes.deviceFace')}
                    value={faceValue}
                    onChange={(e) => setDraft((d) => ({ ...d, [node.id]: { detector: value, face: e.target.value } }))}
                  >
                    <option value="">{t('nodes.auto')}</option>
                    {gpus.map((g) => (
                      <option key={g.idx} value={`cuda:${g.idx}`}>
                        {`cuda:${g.idx}`} — {g.name}
                      </option>
                    ))}
                  </Select>
                  {gpus.length === 0 && (
                    <p style={{ fontSize: 12, color: '#8d8d8d', margin: '4px 0 0' }}>{t('nodes.noGpu')}</p>
                  )}
                </div>
                <Button kind="primary" size="sm" onClick={() => void save(node)}>
                  {t('common.save')}
                </Button>
                {savedId === node.id && (
                  <span style={{ fontSize: 12, color: '#42be65' }}>{t('nodes.saved')}</span>
                )}
              </div>
            </Tile>
          )
        })
      )}
    </div>
  )
}
