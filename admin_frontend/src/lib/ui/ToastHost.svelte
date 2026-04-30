<script lang="ts">
  import { cn } from '$lib/utils';

  export type ToastKind = 'success' | 'error' | 'info' | 'warning';
  export type ToastMessage = { kind: ToastKind; message: string } | null;

  let { toast }: { toast: ToastMessage } = $props();
</script>

{#if toast}
  <div class="pointer-events-none fixed inset-x-4 bottom-4 z-[80] flex justify-end sm:inset-x-auto sm:right-4">
    <div
      class={cn(
        'pointer-events-auto max-w-[min(28rem,calc(100vw-2rem))] rounded-md border bg-popover px-4 py-3 font-sans text-sm font-semibold text-popover-foreground shadow-2xl',
        toast.kind === 'success' &&
          'border-emerald-500/40 bg-emerald-500/15 text-emerald-700 dark:text-emerald-200',
        toast.kind === 'error' && 'border-destructive/40 bg-destructive/15 text-destructive',
        toast.kind === 'warning' &&
          'border-amber-500/40 bg-amber-500/15 text-amber-700 dark:text-amber-200',
        toast.kind === 'info' && 'border-primary/40 bg-primary/15 text-primary'
      )}
      role={toast.kind === 'error' ? 'alert' : 'status'}
      aria-live={toast.kind === 'error' ? 'assertive' : 'polite'}
    >
      {toast.message}
    </div>
  </div>
{/if}
