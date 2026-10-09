import { Tooltip } from '@carbon/react'
import { Information } from '@carbon/icons-react'
import { useT } from '../app/i18n'

/** Ikon info kecil; penjelasan muncul saat hover, fokus keyboard, atau ketuk (ponsel). */
export default function InfoTip({ name, text, align = 'top-start' }: { name: string; text: string; align?: 'top-start' | 'top-end' }) {
  const { t } = useT()
  return (
    <Tooltip description={text} align={align} className="info-tip">
      <button type="button" className="info-tip__btn" aria-label={t('detection.tipLabel', { name })}>
        <Information size={16} />
      </button>
    </Tooltip>
  )
}
