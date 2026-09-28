import type { TKey } from '../../app/i18n'

export const MIN_PASSWORD = 8 // sama dengan backend (schemas/user.py check_password)

export function passwordProblem(pw: string, confirm: string): TKey | null {
  if (pw.length < MIN_PASSWORD) return 'pw.err.short'
  if (new TextEncoder().encode(pw).length > 72) return 'pw.err.long' // batas bcrypt
  if (pw !== confirm) return 'pw.err.mismatch'
  return null
}
