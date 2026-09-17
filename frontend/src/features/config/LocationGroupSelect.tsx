import { Select, SelectItem } from '@carbon/react'
import type { LocationGroup } from '../../api/locationGroups'

export default function LocationGroupSelect({
  groups,
  value,
  onChange,
  emptyLabel,
  labelText,
}: {
  groups: LocationGroup[]
  value: number | ''
  onChange: (value: number | '') => void
  emptyLabel: string
  labelText: string
}) {
  return (
    <Select
      id="wiz-location-group"
      labelText={labelText}
      value={value}
      onChange={(event) => {
        const next = event.target.value
        onChange(next === '' ? '' : Number(next))
      }}
    >
      <SelectItem value="" text={emptyLabel} />
      {groups
        .filter((group) => group.enabled || group.id === value)
        .map((group) => <SelectItem key={group.id} value={group.id} text={group.name} />)}
    </Select>
  )
}
