import { useState } from 'react'
import { Button, InlineNotification, Modal, PasswordInput, Tag, TextInput } from '@carbon/react'
import { useT } from '../../app/i18n'
import { updateCredentialProfile, type CredentialProfile } from '../../api/credentialProfiles'
import NewCredentialForm from './NewCredentialForm'

type Props = {
  profiles: CredentialProfile[]
  onClose: () => void
  onChanged: () => void
}

// Daftar profil kredensial kamera: ubah username/password, (non)aktifkan, tambah baru.
export default function CredentialProfilesModal({ profiles, onClose, onChanged }: Props) {
  const { t } = useT()
  const [editing, setEditing] = useState<CredentialProfile | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const startEdit = (p: CredentialProfile) => {
    setEditing(p)
    setUsername(p.username)
    setPassword('')
    setError(null)
  }

  const saveEdit = async () => {
    if (!editing) return
    setError(null)
    try {
      await updateCredentialProfile(editing.id, { username: username.trim(), ...(password ? { password } : {}) })
      setEditing(null)
      onChanged()
    } catch {
      setError(t('cameras.cred.saveError'))
    }
  }

  const toggle = async (p: CredentialProfile) => {
    setError(null)
    try {
      await updateCredentialProfile(p.id, { enabled: !p.enabled })
      onChanged()
    } catch (e) {
      // 409 = backend menolak karena profil masih dipakai kamera aktif
      setError(t(e instanceof Error && e.message.endsWith(': 409') ? 'cameras.cred.inUse' : 'cameras.cred.saveError'))
    }
  }

  return (
    <Modal open passiveModal size="sm" modalHeading={t('cameras.manageCredentials')} onRequestClose={onClose}
      data-testid="credential-profiles-modal">
      <p style={{ fontSize: 12, marginBottom: 12 }}>{t('cameras.cred.hint')}</p>
      {profiles.length === 0 && <p>{t('cameras.cred.empty')}</p>}
      {profiles.map((p) => (
        <div key={p.id} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', padding: '6px 0' }}>
          <strong style={{ minWidth: 120 }}>{p.name}</strong>
          <span style={{ color: 'var(--cds-text-secondary)' }}>{p.username || '—'}</span>
          {!p.enabled && <Tag size="sm" type="gray">{t('cameras.cred.disabled')}</Tag>}
          <span style={{ flex: 1 }} />
          <Button kind="ghost" size="sm" aria-label={`${t('cameras.edit')} ${p.name}`} onClick={() => startEdit(p)}>
            {t('cameras.edit')}
          </Button>
          <Button kind="ghost" size="sm"
            aria-label={`${t(p.enabled ? 'cameras.cred.disable' : 'cameras.cred.enable')} ${p.name}`}
            onClick={() => void toggle(p)}>
            {t(p.enabled ? 'cameras.cred.disable' : 'cameras.cred.enable')}
          </Button>
        </div>
      ))}
      {editing && (
        <div style={{ borderTop: '1px solid var(--cds-border-subtle)', marginTop: 8, paddingTop: 12 }}>
          <TextInput id="cred-edit-username" labelText={t('cameras.cred.username')} value={username} autoComplete="off"
            onChange={(e) => setUsername(e.target.value)} />
          <PasswordInput id="cred-edit-password" labelText={t('cameras.cred.newPassword')}
            helperText={t('cameras.cred.keepPassword')} value={password} autoComplete="new-password"
            onChange={(e) => setPassword(e.target.value)} style={{ marginTop: 12 }} />
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <Button size="sm" onClick={() => void saveEdit()}>{t('cameras.cred.save')}</Button>
            <Button kind="ghost" size="sm" onClick={() => setEditing(null)}>{t('common.cancel')}</Button>
          </div>
        </div>
      )}
      <Button kind="ghost" size="sm" onClick={() => setAdding(true)} style={{ marginTop: 12 }}>
        {t('cameras.wizard.credentialNew')}
      </Button>
      {error && <InlineNotification kind="error" lowContrast hideCloseButton title={error} style={{ marginTop: 12 }} />}
      {adding && (
        <NewCredentialForm onCancel={() => setAdding(false)} onCreated={() => { setAdding(false); onChanged() }} />
      )}
    </Modal>
  )
}
