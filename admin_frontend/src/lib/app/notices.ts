// The live notices the shared UI kit's own stream ($kit/live) would carry. The admin does not use that stream:
// its pages listen to their own (lib/live/status.svelte.ts and the features' event streams), so only the one
// notice every Hiro app has is named.
export const NOTICE_TYPES = ['hello'] as const;
