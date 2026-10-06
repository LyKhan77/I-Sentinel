import type { ReactNode } from 'react'

type Block =
  | { kind: 'p'; text: string; summary?: boolean }
  | { kind: 'time'; time: string; text: string }
  | { kind: 'li'; text: string }
  | { kind: 'conclusion'; label: string; text: string }

// "0:03 — teks", "- **0:12** - teks", "detik 3,3 — teks" (opsional awalan butir/nomor dan tebal)
const TIME = /^(?:[-*•]\s*|\d+[.)]\s+)?(?:\*\*)?(\d{1,2}:\d{2}(?::\d{2})?|detik\s+\d+(?:[.,]\d+)?)(?:\*\*)?\s*[—–-]\s+(.+)$/i
const CONCLUSION = /^(?:\*\*)?(kesimpulan|ringkasan|catatan)\s*:(?:\*\*)?\s*(.*)$/i
const ITEM = /^(?:[-*•]|\d+[.)])\s+(.*)$/
// label ringkasan pada baris pertama ("Satu kalimat ringkasan:", "Ringkasan:") tidak ikut ditampilkan
const LEAD_LABEL = /^(?:\*\*)?(?:satu kalimat\s+)?(?:ringkasan|summary)\s*:(?:\*\*)?\s*(.+)$/i

function parse(text: string): Block[] {
  const blocks: Block[] = []
  for (const raw of text.split('\n')) {
    const line = raw.trim().replace(/^#{1,6}\s+/, '')
    if (!line) continue
    const lead = blocks.length === 0 ? LEAD_LABEL.exec(line) : null
    if (lead) {
      blocks.push({ kind: 'p', text: lead[1] })
      continue
    }
    const time = TIME.exec(line)
    const conclusion = CONCLUSION.exec(line)
    const item = ITEM.exec(line)
    if (time) blocks.push({ kind: 'time', time: time[1], text: time[2] })
    else if (conclusion) blocks.push({ kind: 'conclusion', label: `${conclusion[1]}:`, text: conclusion[2] })
    else if (item) blocks.push({ kind: 'li', text: item[1] })
    else blocks.push({ kind: 'p', text: line })
  }
  // kalimat pembuka sebelum baris waktu = ringkasan
  const first = blocks[0]
  if (first?.kind === 'p' && blocks.some((b) => b.kind === 'time')) first.summary = true
  return blocks
}

/** **tebal** menjadi <strong>; selebihnya teks biasa (tidak pernah HTML). */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4
      ? <strong key={i}>{part.slice(2, -2)}</strong>
      : part,
  )
}

/**
 * Jawaban LLM sebagai elemen React yang aman: linimasa, daftar, tebal, dan paragraf.
 * Teks apa pun dari model tetap teks (tanpa dangerouslySetInnerHTML); markdown lama ikut rapi.
 */
export default function AiAnswer({ text }: { text: string }) {
  const nodes: ReactNode[] = []
  const blocks = parse(text)
  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i]
    if (block.kind === 'time' || block.kind === 'li') {
      const run: typeof blocks = []
      while (i < blocks.length && blocks[i].kind === block.kind) run.push(blocks[i++])
      i--
      nodes.push(
        <ul key={i} className={block.kind === 'time' ? 'ev-ai-timeline' : 'ev-ai-list'}>
          {run.map((b, j) => b.kind === 'time'
            ? <li key={j}><span className="ev-ai-time">{b.time}</span><span>{inline(b.text)}</span></li>
            : b.kind === 'li' ? <li key={j}>{inline(b.text)}</li> : null)}
        </ul>,
      )
    } else if (block.kind === 'conclusion') {
      nodes.push(<p key={i} className="ev-ai-conclusion"><strong>{block.label}</strong> {inline(block.text)}</p>)
    } else {
      nodes.push(<p key={i} className={block.summary ? 'ev-ai-summary' : 'ev-ai-p'}>{inline(block.text)}</p>)
    }
  }
  return <div className="ev-ai-answer">{nodes}</div>
}
