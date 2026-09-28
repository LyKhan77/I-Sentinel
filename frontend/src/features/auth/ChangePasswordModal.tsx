import { useState } from 'react'
import { InlineNotification, Modal, PasswordInput } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { changePassword } from '../../api/client'
import { passwordProblem } from './password'

/** Ganti password sendiri; sukses → server menulis cookie baru (browser ini tetap login). */
export default function ChangePasswordModal({ onClose }: { onClose: (changed: boolean) => void }) {
  const { t } = useT()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<TKey | null>(null)
  const [busy, setBusy] = useState(false)
  const problem: TKey | null = current ? passwordProblem(next, confirm) : 'pw.err.current'

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await changePassword(current, next)
      onClose(true)
    } catch (e) {
      const m = (e as Error).message
      setError(m === 'wrong' ? 'pw.err.wrong' : m === 'locked' ? 'pw.err.locked' : 'users.err.invalid')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open size="sm" modalHeading={t('pw.title')} primaryButtonText={t('common.save')}
      secondaryButtonText={t('common.cancel')} primaryButtonDisabled={problem !== null || busy}
      onRequestClose={() => onClose(false)} onRequestSubmit={submit}>
      <div className="en-form">
        <PasswordInput id="pw-current" labelText={t('pw.current')} autoComplete="current-password"
          value={current} onChange={(e) => setCurrent(e.target.value)} />
        <PasswordInput id="pw-new" labelText={t('pw.new')} autoComplete="new-password"
          value={next} onChange={(e) => setNext(e.target.value)} />
        <PasswordInput id="pw-confirm" labelText={t('pw.confirm')} autoComplete="new-password"
          value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {problem && next && <p className="en-form__hint">{t(problem)}</p>}
        {error && <InlineNotification kind="error" lowContrast hideCloseButton title={t(error)} />}
      </div>
    </Modal>
  )
}
