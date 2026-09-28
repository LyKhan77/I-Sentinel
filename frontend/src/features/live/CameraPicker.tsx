import { Button, Checkbox } from '@carbon/react'
import { useT } from '../../app/i18n'
import type { Camera } from '../../api/cameras'
import { isSelected, setCameras, type CameraSel } from './screenPrefs'

/** Pilih kamera yang tampil, dikelompokkan per lokasi (checkbox grup = semua kamera di lokasi itu). */
export default function CameraPicker({ cams, value, onChange, open, onOpenChange }: {
  cams: Camera[]
  value: CameraSel
  onChange: (v: CameraSel) => void
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useT()
  const groups = new Map<string, Camera[]>()
  for (const c of cams) groups.set(c.location || '', [...(groups.get(c.location || '') ?? []), c])
  const count = cams.filter((c) => isSelected(value, c.id)).length
  return (
    <div className="lv-picker">
      <Button kind="tertiary" size="sm" data-testid="live-picker-open" aria-expanded={open}
        onClick={() => onOpenChange(!open)}>
        {t('live.picker.button').replace('{n}', String(count)).replace('{m}', String(cams.length))}
      </Button>
      {open && (
        <div className="lv-picker__panel" data-testid="live-picker" role="dialog" aria-label={t('live.picker.title')}>
          <div className="lv-picker__actions">
            <Button kind="ghost" size="sm" data-testid="live-picker-all" onClick={() => onChange({ mode: 'all' })}>
              {t('live.picker.all')}
            </Button>
            <Button kind="ghost" size="sm" data-testid="live-picker-none" onClick={() => onChange({ mode: 'some', ids: [] })}>
              {t('live.picker.none')}
            </Button>
          </div>
          {[...groups].map(([loc, list], i) => {
            const on = list.filter((c) => isSelected(value, c.id)).length
            return (
              <fieldset key={loc} className="lv-picker__group">
                <Checkbox id={`lv-pick-loc-${i}`} labelText={loc || t('live.picker.noLocation')}
                  checked={on === list.length} indeterminate={on > 0 && on < list.length}
                  onChange={(_, { checked }) => onChange(setCameras(value, cams, list.map((c) => c.id), checked))} />
                {list.map((c) => (
                  <Checkbox key={c.id} id={`lv-pick-${c.id}`} labelText={c.name} className="lv-picker__cam"
                    checked={isSelected(value, c.id)}
                    onChange={(_, { checked }) => onChange(setCameras(value, cams, [c.id], checked))} />
                ))}
              </fieldset>
            )
          })}
        </div>
      )}
    </div>
  )
}
