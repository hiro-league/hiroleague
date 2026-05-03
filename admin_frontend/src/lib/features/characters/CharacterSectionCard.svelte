<script lang="ts">
  import type { Snippet } from 'svelte';
  import {
    characterSectionTitleClass,
    characterSectionHintClass
  } from '$lib/features/characters/character-section-classes';

  /**
   * Section shell for character editor blocks.
   *
   * Provide `header` when you need a complex title row (toolbar, multi-line copy). Otherwise pass
   * `title` and optional `hint` for a simple title plus supporting text.
   *
   * Sibling sections that build their own snippet `header`/`hint` should import the shared
   * `character-section-classes` constants to stay visually aligned.
   */
  let {
    title = '',
    hint,
    header,
    children
  }: {
    title?: string;
    hint?: Snippet;
    header?: Snippet;
    children: Snippet;
  } = $props();
</script>

<section
  class="rounded-xl border border-[color-mix(in_oklab,var(--border)_85%,transparent)] bg-[color-mix(in_oklab,var(--card)_72%,transparent)] px-[1.35rem] py-5 shadow-[0_1px_3px_rgb(0_0_0_/_6%)]"
>
  {#if header}
    {@render header()}
  {:else}
    {#if title}
      <h4 class={characterSectionTitleClass}>{title}</h4>
    {/if}
    {#if hint}
      {@render hint()}
    {/if}
  {/if}
  {@render children()}
</section>
