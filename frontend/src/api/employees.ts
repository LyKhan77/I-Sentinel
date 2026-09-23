import { apiFetch } from './client'

export type Employee = {
  id: number
  name: string
  employee_code: string
  active: boolean
  shift_id: number | null
  shift_name: string | null
}

export type EmployeePayload = { name: string; employee_code: string; shift_id: number | null }

export type Shift = {
  id: number
  name: string
  start_time: string
  end_time: string
  tolerance_min: number
  workdays: number[]
}

export type ShiftPayload = { name: string; start_time: string; end_time: string; tolerance_min?: number; workdays?: number[] }

export type Photo = { id: number; quality: number | null; created_at: string; path: string | null }

export type EnrollmentStatus = { photos: number; active: boolean }

async function expectOk(res: Response, what: string) {
  if (!res.ok) throw new Error(`${what} failed: ${res.status}`)
  return res.json()
}

export async function listEmployees(active?: boolean): Promise<Employee[]> {
  const qs = active != null ? `?active=${active}` : ''
  return expectOk(await apiFetch(`/employees${qs}`), 'list employees')
}

export async function createEmployee(payload: EmployeePayload): Promise<Employee> {
  const res = await apiFetch('/employees', { method: 'POST', body: JSON.stringify(payload) })
  if (res.status === 409) throw new Error('duplicate')
  return expectOk(res, 'create employee')
}

export async function updateEmployee(id: number, patch: Partial<EmployeePayload> & { active?: boolean }): Promise<Employee> {
  return expectOk(await apiFetch(`/employees/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }), 'update employee')
}

export async function deleteEmployee(id: number): Promise<void> {
  const res = await apiFetch(`/employees/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`delete employee failed: ${res.status}`)
}

export async function listShifts(): Promise<Shift[]> {
  return expectOk(await apiFetch('/shifts'), 'list shifts')
}

export async function createShift(payload: ShiftPayload): Promise<Shift> {
  return expectOk(await apiFetch('/shifts', { method: 'POST', body: JSON.stringify(payload) }), 'create shift')
}

export async function listPhotos(employeeId: number): Promise<Photo[]> {
  return expectOk(await apiFetch(`/employees/${employeeId}/photos`), 'list photos')
}

export async function uploadPhoto(employeeId: number, file: File): Promise<{ embedding_id: number; quality: number | null }> {
  const fd = new FormData()
  fd.append('file', file)
  return expectOk(await apiFetch(`/employees/${employeeId}/photos`, { method: 'POST', body: fd }), 'upload photo')
}

export type BatchPhotoResult = {
  ok: boolean
  reason?: string
  quality?: number | null
  path?: string | null
  duplicate_of?: { employee_id: number; score: number } | null
}

export async function uploadPhotosBatch(employeeId: number, files: File[]): Promise<{ results: BatchPhotoResult[] }> {
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  return expectOk(await apiFetch(`/employees/${employeeId}/photos/batch`, { method: 'POST', body: fd }), 'upload photos batch')
}

export async function deletePhoto(employeeId: number, embeddingId: number): Promise<void> {
  const res = await apiFetch(`/employees/${employeeId}/photos/${embeddingId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`delete photo failed: ${res.status}`)
}

export async function purgeBiometrics(employeeId: number): Promise<{ deleted: number }> {
  return expectOk(await apiFetch(`/employees/${employeeId}/biometrics`, { method: 'DELETE' }), 'purge biometrics')
}

export async function enrollmentStatus(employeeId: number): Promise<EnrollmentStatus> {
  return expectOk(await apiFetch(`/employees/${employeeId}/enrollment-status`), 'enrollment status')
}
