<script lang="ts">
  /**
   * Single underline tab inside `<Subtabs>`.
   * UI kit, step 7d: a shadcn-svelte Tabs trigger (so it lives inside Subtabs' Tabs): `value` is its tab's id, and
   * the picked one is the one whose value Subtabs holds.
   */
  import type { Snippet } from 'svelte';
  import * as Tabs from '$kit/components/ui/tabs/index.js';
  import { subtabClass } from './subtab-class';

  type Props = {
    value: string;
    label: string;
    /** Optional count shown after the label in a subtle muted color, e.g. Corpus (302). */
    count?: number;
    /** Optional free-text count (e.g. "5/20" → (5/20)); takes precedence over `count`. */
    countText?: string;
    /** Override the count span classes (e.g. an accent color); defaults to the muted style. */
    countClass?: string;
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
    value,
    label,
    count,
    countText,
    countClass = 'ml-1 font-normal text-muted-foreground/70',
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

<Tabs.Trigger
  {value}
  id={htmlId}
  class={subtabClass(className)}
  aria-controls={ariaControls}
  aria-label={ariaLabel}
  {title}
  {disabled}
  {onclick}
>
  {#if children}{@render children()}{:else}{label}{#if countText != null}<span
        class={countClass}>({countText})</span
      >{:else if count != null}<span class={countClass}>({count})</span
      >{/if}{/if}
</Tabs.Trigger>
