// formatBytes mengikuti locale aktif: id-ID → '2,0 kB', en → '2 kB' (Intl memangkas trailing .0)
export function formatBytes(n: number, locale: string): string {
  const units = ['B', 'kB', 'MB', 'GB', 'TB']
  let u = 0
  let v = n
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024
    u++
  }
  const num = new Intl.NumberFormat(locale === 'en' ? 'en' : 'id-ID', { maximumFractionDigits: 1 }).format(v)
  return `${num} ${units[u]}`
}
