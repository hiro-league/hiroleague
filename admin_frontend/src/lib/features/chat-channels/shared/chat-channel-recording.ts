/**
 * MediaRecorder lifecycle shared by Messages tab capture (finalize, discard, page teardown).
 * MIME pick + base64 chunking stay in ``chat-channel-media.ts``.
 */

import { uint8ToBase64 } from './chat-channel-media';

/** Wait for ``stop`` then end all tracks (mic LED / resource cleanup). */
export async function stopMediaRecorderAndDetach(mr: MediaRecorder): Promise<void> {
  await new Promise<void>((resolve) => {
    mr.addEventListener('stop', () => resolve(), { once: true });
    try {
      mr.stop();
    } catch {
      resolve();
    }
  });
  for (const t of mr.stream.getTracks()) {
    try {
      t.stop();
    } catch {
      /* ignore */
    }
  }
}

export function buildRecordingBlobFromChunks(
  chunks: Blob[],
  recorderMimeType: string
): { blob: Blob; effectiveMime: string } {
  const effectiveMime = recorderMimeType || chunks[0]?.type || 'audio/webm';
  return { blob: new Blob(chunks, { type: effectiveMime }), effectiveMime };
}

export async function recordingBlobToBase64(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer();
  return uint8ToBase64(new Uint8Array(buf));
}
