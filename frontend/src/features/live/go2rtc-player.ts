// Player go2rtc untuk tile live view.
//
// Vendor: video-rtc.js v1.6.0 — file resmi go2rtc, di-copy tanpa perubahan
// (polanya sama dengan ActivityTracking-AI yang sudah terbukti di LAN yang sama).
// Deklarasi tipenya di video-rtc.d.ts. Wrapper di bawah hanya menyetel perilaku
// tile: tanpa kontrol bawaan (tile punya overlay sendiri, fullscreen via dblclick),
// muted autoplay, object-fit cover.
import 'react'

import { VideoRTC } from './video-rtc.js'

class VideoStream extends VideoRTC {
  oninit() {
    super.oninit()
    this.video.controls = false
    this.video.muted = true
    this.video.style.objectFit = 'cover'
    this.media = 'video' // tanpa audio decode; tile selalu muted
  }
}

if (typeof window !== 'undefined' && !customElements.get('video-stream')) {
  customElements.define('video-stream', VideoStream)
}

export type StreamElement = HTMLElement & {
  mode?: string
  media?: string
  src?: string
  video?: HTMLVideoElement
}

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'video-stream': React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement>
    }
  }
}
