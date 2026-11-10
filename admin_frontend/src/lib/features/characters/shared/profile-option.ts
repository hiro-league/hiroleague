/** One AI or voice profile a character's ordered list can pick (Phase 7b step 5). */
export type ProfileOption = {
  id: string;
  label: string;
  /** "Google · Gemini 3.8 Flash · temperature 0.3 · …" / "Google · Gemini TTS · Kore". */
  line: string;
  /** A caution shown with it (e.g. a plan tool's model, which chat skips); null = none. */
  note: string | null;
};
