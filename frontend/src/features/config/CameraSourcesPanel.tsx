import { useState } from 'react'
import {
  Button,
  InlineNotification,
  NumberInput,
  Select,
  SelectItem,
  TextInput,
} from '@carbon/react'
import { useT } from '../../app/i18n'
import {
  createCredentialProfile,
  updateCredentialProfile,
  type CredentialProfile,
} from '../../api/credentialProfiles'
import {
  createLocationGroup,
  updateLocationGroup,
  type LocationGroup,
} from '../../api/locationGroups'
import {
  createStreamSource,
  updateStreamSource,
  type SourceKind,
  type StreamSource,
} from '../../api/streamSources'

type Props = {
  sources: StreamSource[]
  groups: LocationGroup[]
  profiles: CredentialProfile[]
  onChanged: () => Promise<void>
}

export default function CameraSourcesPanel({ sources, groups, profiles, onChanged }: Props) {
  const { t } = useT()
  const [sourceName, setSourceName] = useState('')
  const [sourceKind, setSourceKind] = useState<SourceKind>('nvr')
  const [sourceHost, setSourceHost] = useState('')
  const [sourcePort, setSourcePort] = useState('554')
  const [sourceCredential, setSourceCredential] = useState('')
  const [groupName, setGroupName] = useState('')
  const [profileName, setProfileName] = useState('')
  const [profileUsername, setProfileUsername] = useState('')
  const [profileRef, setProfileRef] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      await onChanged()
    } catch {
      setError(t('cameras.sources.saveError'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section data-testid="camera-sources-panel" style={{ borderTop: '1px solid var(--cds-border-subtle)', margin: '16px 0', paddingTop: 12 }}>
      <h3 style={{ margin: '0 0 10px' }}>{t('cameras.sources.title')}</h3>
      {error && <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={error} onCloseButtonClick={() => setError(null)} />}
      <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <TextInput id="source-name" labelText={t('cameras.sources.name')} value={sourceName} onChange={(event) => setSourceName(event.target.value)} />
        <Select id="source-kind" labelText={t('cameras.sources.kind')} value={sourceKind} onChange={(event) => setSourceKind(event.target.value as SourceKind)}>
          <SelectItem value="nvr" text="NVR" />
          <SelectItem value="ip_camera" text={t('cameras.sources.ipCamera')} />
          <SelectItem value="unknown" text={t('cameras.sources.unknown')} />
        </Select>
        <TextInput id="source-host" labelText={t('cameras.sources.host')} value={sourceHost} onChange={(event) => setSourceHost(event.target.value)} />
        <NumberInput id="source-port" label={t('cameras.sources.port')} value={sourcePort} min={1} max={65535} onChange={(_, state) => setSourcePort(String(state.value ?? ''))} />
        <Select id="source-credential" labelText={t('cameras.sources.defaultCredential')} value={sourceCredential} onChange={(event) => setSourceCredential(event.target.value)}>
          <SelectItem value="" text={t('cameras.sources.none')} />
          {profiles.filter((profile) => profile.enabled).map((profile) => <SelectItem key={profile.id} value={profile.id} text={profile.name} />)}
        </Select>
        <Button
          data-testid="source-create"
          disabled={busy || !sourceName.trim() || !sourceHost.trim()}
          onClick={() => void run(async () => {
            await createStreamSource({
              name: sourceName.trim(),
              kind: sourceKind,
              host: sourceHost.trim(),
              port: Number(sourcePort) || 554,
              default_credential_id: sourceCredential ? Number(sourceCredential) : null,
            })
            setSourceName('')
            setSourceHost('')
          })}
        >
          {t('cameras.sources.addSource')}
        </Button>
      </div>
      <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', marginTop: 10 }}>
        <TextInput id="group-name" labelText={t('cameras.sources.groupName')} value={groupName} onChange={(event) => setGroupName(event.target.value)} />
        <Button
          data-testid="group-create"
          disabled={busy || !groupName.trim()}
          onClick={() => void run(async () => {
            await createLocationGroup({ name: groupName.trim() })
            setGroupName('')
          })}
        >
          {t('cameras.sources.addGroup')}
        </Button>
        <TextInput id="profile-name" labelText={t('cameras.sources.profile')} value={profileName} onChange={(event) => setProfileName(event.target.value)} />
        <TextInput id="profile-username" labelText={t('cameras.sources.username')} value={profileUsername} onChange={(event) => setProfileUsername(event.target.value)} />
        <TextInput id="profile-ref" labelText={t('cameras.sources.secretRef')} value={profileRef} onChange={(event) => setProfileRef(event.target.value)} />
        <Button
          data-testid="profile-create"
          disabled={busy || !profileName.trim() || !profileRef.trim()}
          onClick={() => void run(async () => {
            await createCredentialProfile({ name: profileName.trim(), username: profileUsername.trim(), secret_ref: profileRef.trim() })
            setProfileName('')
            setProfileUsername('')
            setProfileRef('')
          })}
        >
          {t('cameras.sources.addProfile')}
        </Button>
      </div>
      {(sources.length > 0 || groups.length > 0 || profiles.length > 0) && (
        <div style={{ display: 'grid', gap: 4, marginTop: 12, fontSize: 12 }}>
          {sources.map((source) => (
            <div key={`source-${source.id}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span>{source.name} · {source.host}:{source.port}{source.default_credential_id ? ` · ${profiles.find((profile) => profile.id === source.default_credential_id)?.name ?? ''}` : ''}</span>
              <Button kind="ghost" size="sm" disabled={busy} onClick={() => void run(() => updateStreamSource(source.id, { enabled: !source.enabled }))}>
                {source.enabled ? t('cameras.sources.disable') : t('cameras.sources.enable')}
              </Button>
            </div>
          ))}
          {groups.map((group) => (
            <div key={`group-${group.id}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span>{group.name}</span>
              <Button kind="ghost" size="sm" disabled={busy} onClick={() => void run(() => updateLocationGroup(group.id, { enabled: !group.enabled }))}>
                {group.enabled ? t('cameras.sources.disable') : t('cameras.sources.enable')}
              </Button>
            </div>
          ))}
          {profiles.map((profile) => (
            <div key={`profile-${profile.id}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span>{profile.name} · {profile.username} · {profile.secret_ref}</span>
              <Button kind="ghost" size="sm" disabled={busy} onClick={() => void run(() => updateCredentialProfile(profile.id, { enabled: !profile.enabled }))}>
                {profile.enabled ? t('cameras.sources.disable') : t('cameras.sources.enable')}
              </Button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
