import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, TextInput, PasswordInput, InlineNotification, Stack } from '@carbon/react'
import { useT } from '../../app/i18n'
import { login } from '../../api/client'

// Hanya path internal: tolak //host, /\\host, dan URL absolut (open redirect).
function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\') ? next : '/dashboard'
}

export default function LoginPage() {
  const { t } = useT()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ username?: string; password?: string }>({})
  const [apiError, setApiError] = useState<'invalid' | 'disabled' | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const errs: typeof errors = {}
    if (!username.trim()) errs.username = t('login.required')
    if (!password.trim()) errs.password = t('login.required')
    setErrors(errs)
    if (Object.keys(errs).length > 0) return
    setBusy(true)
    setApiError(null)
    try {
      await login(username, password)
      navigate(safeNext(params.get('next')))
    } catch (e) {
      setApiError((e as Error).message === 'disabled' ? 'disabled' : 'invalid')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <div className="login__panel">
        <div className="login__brand">
          <span className="app-logo-mark" aria-hidden="true">
            IS
          </span>
          I-Sentinel
        </div>
        <h1 className="login__title">{t('login.title')}</h1>
        <p className="login__sub">{t('login.sub')}</p>
        {apiError && (
          <InlineNotification
            kind="error"
            lowContrast
            title={t(apiError === 'disabled' ? 'login.disabled' : 'login.invalid')}
            subtitle=""
            onCloseButtonClick={() => setApiError(null)}
          />
        )}
        <form onSubmit={onSubmit}>
          <Stack gap={5}>
            <TextInput
              id="username"
              autoComplete="username"
              labelText={t('login.username')}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              invalid={!!errors.username}
              invalidText={errors.username}
            />
            <PasswordInput
              id="password"
              autoComplete="current-password"
              labelText={t('login.password')}
              showPasswordLabel={t('login.showPassword')}
              hidePasswordLabel={t('login.hidePassword')}
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
    </div>
  )
}
