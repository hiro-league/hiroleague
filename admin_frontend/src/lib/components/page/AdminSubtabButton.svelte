<script lang="ts">
  /**
   * Single underline tab inside `<AdminSubtabStrip>`. Also used directly for
   * dynamic subtabs (Graph runs open-run inspectors with a close affordance).
   */
  import type { Snippet } from 'svelte';
  import { cnAdminSubtab } from '$lib/styling/admin-tokens';

  type Props = {
    label: string;
    /** Optional count shown after the label in a subtle muted color, e.g. Corpus (302). */
    count?: number;
    /** Optional free-text count (e.g. "5/20" → (5/20)); takes precedence over `count`. */
    countText?: string;
    /** Override the count span classes (e.g. an accent color); defaults to the muted style. */
    countClass?: string;
    active: boolean;
    disabled?: boolean;
    ariaControls?: string;
    ariaLabel?: string;
    htmlId?: string;
    title?: string;
    /** Extra classes (e.g. wider max-width on dynamic record tabs). */
    class?: string;
    onclick?: () => void;
    children?: Snippet;
  };

  let {
    label,
    count,
    countText,
    countClass = 'ml-1 font-normal text-muted-foreground/70',
    active,
    disabled = false,
    ariaControls,
    ariaLabel,
    htmlId,
    title,
    class: className,
    onclick,
    children
  }: Props = $props();
</script>

<button
  type="button"
  id={htmlId}
  class={cnAdminSubtab(active, className)}
  role="tab"
  aria-selected={active}
  aria-controls={ariaControls}
  aria-label={ariaLabel}
  {title}
  {disabled}
  tabindex={disabled ? -1 : 0}
  {onclick}
>
  {#if children}{@render children()}{:else}{label}{#if countText != null}<span
        class={countClass}>({countText})</span
      >{:else if count != null}<span class={countClass}>({count})</span
      >{/if}{/if}
</button>
