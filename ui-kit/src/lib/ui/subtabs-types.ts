// The tabs a Subtabs strip is given. UI kit, step 3: from the HiroLeague admin.

/** Second-level underline tab (Preferences sections, Graph runs ledger strip). */
export type SubtabDescriptor<TId extends string = string> = {
  id: TId;
  label: string;
  /** Optional count rendered after the label in a subtle muted color, e.g. Corpus (302). */
  count?: number;
  /** Optional free-text count after the label, in the same muted style, e.g. "5/20" → (5/20).
   *  Takes precedence over `count` when both are set. */
  countText?: string;
  /** Override the count span's classes (e.g. an accent color); defaults to the muted style. */
  countClass?: string;
  disabled?: boolean;
  ariaLabel?: string;
  htmlId?: string;
  ariaControls?: string;
  /** Native `title` tooltip (e.g. truncated run id on dynamic Graph runs tabs). */
  title?: string;
};
