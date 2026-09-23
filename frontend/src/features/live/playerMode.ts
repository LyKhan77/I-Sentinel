/** Transport aktif player go2rtc: WebRTC memakai srcObject, MSE memakai blob URL. */
export function playerMode(video: Pick<HTMLVideoElement, 'srcObject' | 'src'> | null): 'WebRTC' | 'MSE' | null {
  if (!video) return null
  if (video.srcObject) return 'WebRTC'
  if (video.src?.startsWith('blob:')) return 'MSE'
  return null
}
