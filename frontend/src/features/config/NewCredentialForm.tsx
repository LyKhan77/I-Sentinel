import { useState } from 'react'
import { Button, InlineNotification, PasswordInput, TextInput } from '@carbon/react'
import { useT } from '../../app/i18n'
import { createCredentialProfile, type CredentialProfile } from '../../api/credentialProfiles'

type Props = {
  onCancel: () => void
  onCreated: (profile: CredentialProfile) => void
}

// Form inline (bukan modal: modal bertumpuk di atas wizard berebut fokus). Supervisor mengisi
// username/password kamera sekali, lalu memilih namanya di form kamera.
export default function NewCredentialForm({ onCancel, onCreated }: Props) {
  const { t } = useT()
  const [name, setName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const canSave = name.trim() !== '' && password !== '' && !busy

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const usernameTrim = username.trim()
      onCreated(await createCredentialProfile({
        name: name.trim(),
        ...(usernameTrim !== '' && { username: usernameTrim }),
        password,
      }))
    } catch (e) {
      setError(t(e instanceof Error && e.message.endsWith(': 409') ? 'cameras.cred.duplicate' : 'cameras.cred.saveError'))
      setBusy(false)
    }
  }

  return (
    <fieldset data-testid="new-credential-form"
      style={{ border: '1px solid var(--cds-border-subtle)', padding: 12, marginTop: 8, minWidth: 0 }}>
      <legend style={{ fontSize: 12, padding: '0 4px' }}>{t('cameras.cred.title')}</legend>
      <TextInput id="cred-name" labelText={t('cameras.cred.name')} placeholder="ZKteco" value={name}
        onChange={(e) => setName(e.target.value)} />
      <TextInput id="cred-username" labelText={t('cameras.cred.username')} value={username} autoComplete="off"
        onChange={(e) => setUsername(e.target.value)} style={{ marginTop: 12 }} />
      <PasswordInput id="cred-password" labelText={t('cameras.cred.password')} value={password} autoComplete="new-password"
        onChange={(e) => setPassword(e.target.value)} style={{ marginTop: 12 }} />
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <Button size="sm" disabled={!canSave} onClick={() => void save()}>{t('cameras.cred.save')}</Button>
        <Button size="sm" kind="ghost" onClick={onCancel}>{t('common.cancel')}</Button>
      </div>
      {error && <InlineNotification kind="error" lowContrast hideCloseButton title={error} style={{ marginTop: 12 }} />}
    </fieldset>
  )
}
