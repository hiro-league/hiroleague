import type { CatalogProviderFreeOffer, CatalogProviderRow } from '$lib/api/catalog';

/** Lookup free-offer rows by provider id for active-provider tables. */
export function catalogFreeOffersByProviderId(
  providers: CatalogProviderRow[]
): Record<string, CatalogProviderFreeOffer[]> {
  const out: Record<string, CatalogProviderFreeOffer[]> = {};
  for (const provider of providers) {
    const offers = provider.free_offers?.filter(
      (o) => o.label?.trim() && o.summary?.trim() && o.updated_at?.trim()
    );
    if (offers?.length) {
      out[provider.id] = offers;
    }
  }
  return out;
}
