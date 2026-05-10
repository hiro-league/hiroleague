/**
 * Browser recording helpers — shared with ChatChannels mic pipeline (parity with mobile WebM/opus → base64).
 */

const RECORDING_MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'] as const;

/** First supported MIME type for MediaRecorder, or undefined if unsupported. */
export function pickRecordingMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  for (const c of RECORDING_MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(c)) return c;
  }
  return undefined;
}

/** Binary → base64 without blowing the stack on large blobs. */
export function uint8ToBase64(u8: Uint8Array): string {
  let binary = '';
  const chunkSize = 0x8000;
  for (let i = 0; i < u8.length; i += chunkSize) {
    binary += String.fromCharCode(...u8.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}
