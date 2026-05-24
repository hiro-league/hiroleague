export type DialogCloseSource = 'backdrop' | 'escape' | 'header';

/** Map bits-ui dismiss attempts to the legacy Modal ``onBeforeClose`` shape. */
export function dialogCloseAllowed(
  onBeforeClose: ((source: DialogCloseSource) => boolean) | undefined,
  source: DialogCloseSource
): boolean {
  return !onBeforeClose || onBeforeClose(source);
}
