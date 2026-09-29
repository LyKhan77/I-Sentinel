// Beep pendek tanpa file audio (Web Audio). AudioContext tidak ada / autoplay diblokir → diam.
let ctx: AudioContext | null = null

function audioCtor(): typeof AudioContext | null {
  if (typeof window === 'undefined') return null
  if (typeof window.AudioContext === 'function') return window.AudioContext
  // Safari lama hanya menyediakan prefiks webkitAudioContext (tidak ada di tipe DOM)
  if ('webkitAudioContext' in window) {
    const legacy: unknown = window.webkitAudioContext
    return typeof legacy === 'function' ? (legacy as typeof AudioContext) : null
  }
  return null
}

export function beep(): void {
  try {
    const AC = audioCtor()
    if (!AC) return
    ctx ??= new AC()
    if (ctx.state === 'suspended') void ctx.resume().catch(() => {})
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.frequency.value = 880
    gain.gain.value = 0.15
    osc.connect(gain).connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.15)
  } catch {
    // browser menolak audio → notifikasi visual tetap jalan
  }
}
