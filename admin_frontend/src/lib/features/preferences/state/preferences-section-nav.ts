/** Deep-link target for tuning profile editor (character edit → preferences). */
export const TUNING_PROFILES_SECTION_ID = 'preferences-tuning-profiles';

export type PreferenceSectionId =
  | 'preferences-models'
  | 'preferences-media'
  | 'preferences-memory'
  | 'preferences-knowledge'
  | typeof TUNING_PROFILES_SECTION_ID;

export const PREFERENCE_SECTION_NAV: { id: PreferenceSectionId; label: string }[] = [
  { id: 'preferences-models', label: 'Models' },
  { id: 'preferences-media', label: 'Media' },
  { id: 'preferences-memory', label: 'Agent Memory' },
  { id: 'preferences-knowledge', label: 'Knowledge' },
  { id: TUNING_PROFILES_SECTION_ID, label: 'Tuning profiles' }
];

/**
 * Pixel offset for scroll-spy marker — shell header (64px) plus approximate
 * sticky page header + section-nav toolbar height.
 */
export const PREFERENCE_SECTION_SCROLL_MARKER_PX = 160;
