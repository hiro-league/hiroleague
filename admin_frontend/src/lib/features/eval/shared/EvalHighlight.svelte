<!--
  Highlights the active search term inside a text span (no {@html} — segments are plain text
  wrapped in <mark>, so corpus content can't inject). Identity render when `term` is empty.
  Replaces the per-panel `hl` / `hlR` snippets, which couldn't be shared across component files.
-->
<script lang="ts">
  import { highlightSegments } from '$lib/features/eval/shared/eval-highlight';

  interface Props {
    text: string | null | undefined;
    term: string;
  }
  let { text, term }: Props = $props();
</script>

{#each highlightSegments(text ?? '', term) as seg}{#if seg.hit}<mark
      class="rounded bg-amber-200 text-inherit dark:bg-amber-500/40">{seg.text}</mark
    >{:else}{seg.text}{/if}{/each}
