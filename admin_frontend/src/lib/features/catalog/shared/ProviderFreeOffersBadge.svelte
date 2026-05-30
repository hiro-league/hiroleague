<script lang="ts">
  import { ExternalLink, Gift } from '@lucide/svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import Button from '$lib/components/ui/button.svelte';
  import type { CatalogProviderFreeOffer } from '$lib/api/catalog';
  import { catalogMultilineParagraphs } from '$lib/features/catalog/shared/format-catalog-multiline';

  type Props = {
    providerDisplayName: string;
    offers: CatalogProviderFreeOffer[];
  };

  let { providerDisplayName, offers }: Props = $props();

  let dialogOpen = $state(false);

  const hasOffers = $derived(offers.length > 0);
  const badgeTitle = $derived(
    offers.length === 1
      ? offers[0].summary
      : `${offers.length} free offers — ${offers.map((o) => o.label).join(', ')}`
  );

  function detailParagraphs(offer: CatalogProviderFreeOffer): string[] {
    if (!offer.details?.trim()) return [];
    return catalogMultilineParagraphs(offer.details);
  }
</script>

{#if hasOffers}
  <Button
    type="button"
    variant="ghost"
    size="icon"
    class="relative size-7 shrink-0 text-amber-600 hover:bg-amber-500/10 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
    title={badgeTitle}
    aria-label={`Free offers for ${providerDisplayName}`}
    onclick={(event) => {
      event.stopPropagation();
      dialogOpen = true;
    }}
  >
    <Gift size={15} aria-hidden="true" />
    {#if offers.length > 1}
      <span
        class="pointer-events-none absolute -right-0.5 -top-0.5 flex size-3.5 items-center justify-center rounded-full bg-amber-600 text-[9px] font-semibold text-white dark:bg-amber-500"
        aria-hidden="true"
      >
        {offers.length}
      </span>
    {/if}
  </Button>

  <Dialog.Root bind:open={dialogOpen}>
    <Dialog.Content class="sm:max-w-lg">
      <Dialog.Header>
        <Dialog.Title>Free offers — {providerDisplayName}</Dialog.Title>
        <Dialog.Description class="sr-only">
          Bundled catalog notes for {providerDisplayName}. Verify limits on the vendor site before production use.
        </Dialog.Description>
      </Dialog.Header>
      <ul class="grid max-h-[min(60vh,24rem)] gap-4 overflow-y-auto py-1">
        {#each offers as offer, index (offer.label + index)}
          {@const paragraphs = detailParagraphs(offer)}
          <li class="rounded-md border bg-muted/30 p-4">
            <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <h4 class="font-sans text-sm font-semibold">{offer.label}</h4>
              <time class="shrink-0 text-xs text-muted-foreground" datetime={offer.updated_at}>
                Last updated {offer.updated_at}
              </time>
            </div>
            {#if paragraphs.length > 0}
              <div class="mt-3 space-y-2">
                {#each paragraphs as paragraph (paragraph)}
                  <p class="font-sans text-sm leading-relaxed text-foreground">{paragraph}</p>
                {/each}
              </div>
            {/if}
            {#if offer.details_url}
              <a
                class="mt-3 inline-flex items-center gap-1 font-sans text-sm text-primary hover:underline"
                href={offer.details_url}
                rel="noopener noreferrer"
                target="_blank"
              >
                View vendor details
                <ExternalLink size={14} aria-hidden="true" />
              </a>
            {/if}
          </li>
        {/each}
      </ul>
      <Dialog.Footer>
        <Button type="button" variant="outline" onclick={() => (dialogOpen = false)}>Close</Button>
      </Dialog.Footer>
    </Dialog.Content>
  </Dialog.Root>
{/if}
