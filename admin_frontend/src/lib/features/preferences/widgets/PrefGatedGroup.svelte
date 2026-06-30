<script lang="ts">
  /**
   * A gated region: natively disables (and dims) all its children when `active` is false. Replaces
   * the per-field `<div class="opacity-50"><Field disabled={…}/></div>` pattern — one `<fieldset>`
   * disables every descendant control at once (matching the GraphReranker gate and the manifest's
   * `gated` spec), so children no longer repeat the gate in their own `disabled` props.
   *
   * Default layout is a stacked `grid gap-2` cell (it usually sits in a `PrefFieldGrid`); pass `class`
   * to override.
   */
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Props = {
    /** When false, the group is disabled + dimmed. */
    active?: boolean;
    class?: string;
    children: Snippet;
  };

  let { active = true, class: className = 'grid gap-2', children }: Props = $props();
</script>

<fieldset disabled={!active} class={cn('border-0 p-0', !active && 'opacity-50', className)}>
  {@render children()}
</fieldset>
