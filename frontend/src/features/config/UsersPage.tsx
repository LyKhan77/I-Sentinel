import { useCallback, useEffect, useState } from 'react'
import {
  Button, InlineLoading, InlineNotification, Modal, PasswordInput, Select, SelectItem,
  Table, TableBody, TableCell, TableContainer, TableHead, TableHeader, TableRow, Tag, TextInput,
} from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { createUser, deleteUser, listUsers, updateUser, type Role, type User } from '../../api/users'
import { passwordProblem } from '../auth/password'

const USERNAME_RE = /^[A-Za-z0-9._-]{3,64}$/
const HEADERS = ['users.col.username', 'users.col.role', 'users.col.status', 'users.col.created',
  'users.col.lastLogin', 'users.col.actions'] as const
// pesan backend stabil (app/api/users.py) → teks UI
const ERRORS: [string, TKey][] = [
  ['username taken', 'users.err.taken'], ['yourself', 'users.err.self'], ['your own', 'users.err.self'],
  ['last admin', 'users.err.lastAdmin'], ['invalid', 'users.err.invalid'],
]
const errKey = (msg: string): TKey => ERRORS.find(([s]) => msg.includes(s))?.[1] ?? 'users.err.generic'

type Dialog = { kind: 'add' } | { kind: 'reset' | 'deactivate' | 'delete'; user: User }
const PRIMARY: Record<Dialog['kind'], TKey> = {
  add: 'common.save', reset: 'users.reset', deactivate: 'users.deactivate', delete: 'users.delete',
}
const EMPTY = { username: '', role: 'viewer' as Role, password: '', confirm: '' }

export default function UsersPage({ meId }: { meId?: number }) {
  const { t, locale } = useT()
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<TKey | null>(null)
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const [dialogError, setDialogError] = useState<TKey | null>(null)
  const [form, setForm] = useState(EMPTY)

  const refresh = useCallback(async () => {
    try {
      setUsers(await listUsers())
    } catch {
      setError('users.err.load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- refresh async: setState setelah await
    refresh()
  }, [refresh])

  const open = (d: Dialog) => {
    setDialog(d)
    setDialogError(null)
    setForm(EMPTY)
  }

  const run = async (fn: () => Promise<unknown>, inDialog: boolean) => {
    try {
      await fn()
      setDialog(null)
      setError(null)
      await refresh()
    } catch (e) {
      const key = errKey((e as Error).message)
      if (inDialog) setDialogError(key)
      else setError(key)
    }
  }

  const submit = () => {
    if (!dialog) return
    if (dialog.kind === 'add') return run(() => createUser({ username: form.username, role: form.role, password: form.password }), true)
    if (dialog.kind === 'reset') return run(() => updateUser(dialog.user.id, { password: form.password }), true)
    if (dialog.kind === 'deactivate') return run(() => updateUser(dialog.user.id, { is_active: false }), true)
    return run(() => deleteUser(dialog.user.id), true)
  }

  const problem: TKey | null = dialog?.kind === 'add'
    ? (USERNAME_RE.test(form.username) ? passwordProblem(form.password, form.confirm) : 'users.err.username')
    : dialog?.kind === 'reset' ? passwordProblem(form.password, form.confirm) : null

  const fmt = (iso: string | null) => (iso
    ? new Date(iso).toLocaleString(locale === 'en' ? 'en-GB' : 'id-ID', { dateStyle: 'medium', timeStyle: 'short' })
    : '—')

  const passwordFields = (
    <>
      <PasswordInput id="user-password" labelText={t('users.password')} autoComplete="new-password"
        value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
      <PasswordInput id="user-confirm" labelText={t('users.confirm')} autoComplete="new-password"
        value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
    </>
  )

  return (
    <div>
      {error && <InlineNotification kind="error" lowContrast title={t(error)} onCloseButtonClick={() => setError(null)} />}
      <div className="en-toolbar">
        <Button size="sm" data-testid="user-add" onClick={() => open({ kind: 'add' })}>{t('users.add')}</Button>
      </div>
      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : (
        <div className="en-table-scroll">
          <TableContainer>
            <Table size="sm">
              <TableHead>
                <TableRow>{HEADERS.map((h) => <TableHeader key={h}>{t(h)}</TableHeader>)}</TableRow>
              </TableHead>
              <TableBody>
                {users.map((u) => {
                  const self = u.id === meId
                  return (
                    <TableRow key={u.id} data-testid={`user-row-${u.id}`}>
                      <TableCell>
                        <strong>{u.username}</strong>
                        {self && <span className="en-muted"> {t('users.you')}</span>}
                      </TableCell>
                      <TableCell><Tag size="sm" type={u.role === 'admin' ? 'red' : 'gray'}>{u.role}</Tag></TableCell>
                      <TableCell>
                        {u.is_active ? t('users.active') : <Tag size="sm" type="warm-gray">{t('users.inactive')}</Tag>}
                      </TableCell>
                      <TableCell>{fmt(u.created_at)}</TableCell>
                      <TableCell>{fmt(u.last_login_at)}</TableCell>
                      <TableCell>
                        <Button kind="ghost" size="sm" data-testid={`user-role-${u.id}`} disabled={self}
                          onClick={() => run(() => updateUser(u.id, { role: u.role === 'admin' ? 'viewer' : 'admin' }), false)}>
                          {t(u.role === 'admin' ? 'users.makeViewer' : 'users.makeAdmin')}
                        </Button>
                        <Button kind="ghost" size="sm" data-testid={`user-reset-${u.id}`} disabled={self}
                          onClick={() => open({ kind: 'reset', user: u })}>
                          {t('users.reset')}
                        </Button>
                        {u.is_active ? (
                          <Button kind="ghost" size="sm" data-testid={`user-deactivate-${u.id}`} disabled={self}
                            onClick={() => open({ kind: 'deactivate', user: u })}>
                            {t('users.deactivate')}
                          </Button>
                        ) : (
                          <Button kind="ghost" size="sm" data-testid={`user-activate-${u.id}`}
                            onClick={() => run(() => updateUser(u.id, { is_active: true }), false)}>
                            {t('users.activate')}
                          </Button>
                        )}
                        <Button kind="danger--ghost" size="sm" data-testid={`user-delete-${u.id}`} disabled={self}
                          onClick={() => open({ kind: 'delete', user: u })}>
                          {t('users.delete')}
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </div>
      )}
      <p className="en-muted">{t('users.hint')}</p>

      {dialog && (
        <Modal
          open
          size="sm"
          danger={dialog.kind === 'deactivate' || dialog.kind === 'delete'}
          modalHeading={t(`users.dlg.${dialog.kind}` as TKey)}
          primaryButtonText={t(PRIMARY[dialog.kind])}
          secondaryButtonText={t('common.cancel')}
          primaryButtonDisabled={problem !== null}
          onRequestClose={() => setDialog(null)}
          onRequestSubmit={submit}
        >
          <div className="en-form">
            {dialog.kind === 'add' && (
              <>
                <TextInput id="user-username" labelText={t('users.col.username')} autoComplete="off"
                  value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value.trim() })} />
                <Select id="user-role" labelText={t('users.col.role')} value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                  <SelectItem value="viewer" text={t('users.role.viewer')} />
                  <SelectItem value="admin" text={t('users.role.admin')} />
                </Select>
                {passwordFields}
              </>
            )}
            {dialog.kind === 'reset' && (
              <>
                <p>{t('users.resetBody').replace('{name}', dialog.user.username)}</p>
                {passwordFields}
              </>
            )}
            {dialog.kind === 'deactivate' && <p>{t('users.deactivateBody').replace('{name}', dialog.user.username)}</p>}
            {dialog.kind === 'delete' && <p>{t('users.deleteBody').replace('{name}', dialog.user.username)}</p>}
            {problem && (form.username || form.password) && (
              <p className="en-form__hint" data-testid="user-form-problem">{t(problem)}</p>
            )}
            {dialogError && <InlineNotification kind="error" lowContrast hideCloseButton title={t(dialogError)} />}
          </div>
        </Modal>
      )}
    </div>
  )
}
