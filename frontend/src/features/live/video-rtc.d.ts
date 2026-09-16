// Deklarasi tipe minimal untuk vendor video-rtc.js (player resmi go2rtc v1.6.0).
// Hanya anggota yang dipakai I-Sentinel; sisanya dipakai internal player.
export declare class VideoRTC extends HTMLElement {
  mode: string
  media: string
  src: string
  wsURL: string
  video: HTMLVideoElement
  oninit(): void
}
