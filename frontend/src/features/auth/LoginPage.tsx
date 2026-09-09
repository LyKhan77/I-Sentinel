import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, TextInput, InlineNotification, Stack } from '@carbon/react'
import { useT } from '../../app/i18n'
import { login } from '../../api/client'

export default function LoginPage() {
  const { t } = useT()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ username?: string; password?: string }>({})
  const [apiError, setApiError] = useState(false)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const errs: typeof errors = {}
    if (!username.trim()) errs.username = t('login.required')
    if (!password.trim()) errs.password = t('login.required')
    setErrors(errs)
    if (Object.keys(errs).length > 0) return
    setBusy(true)
    setApiError(false)
    try {
      await login(username, password)
      navigate('/dashboard')
    } catch {
      setApiError(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: '96px auto', padding: '0 16px' }}>
      <h1 style={{ fontSize: 24, fontWeight: 300, marginBottom: 24 }}>{t('login.title')}</h1>
      {apiError && (
        <InlineNotification
          kind="error"
          lowContrast
          title={t('login.invalid')}
          subtitle=""
          onCloseButtonClick={() => setApiError(false)}
        />
      )}
      <form onSubmit={onSubmit}>
        <Stack gap={5}>
          <TextInput
            id="username"
            labelText={t('login.username')}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            invalid={!!errors.username}
            invalidText={errors.username}
          />
          <TextInput
            id="password"
            type="password"
            labelText={t('login.password')}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            invalid={!!errors.password}
            invalidText={errors.password}
          />
          <Button type="submit" disabled={busy}>
            {t('login.submit')}
          </Button>
        </Stack>
      </form>
    </div>
  )
}
