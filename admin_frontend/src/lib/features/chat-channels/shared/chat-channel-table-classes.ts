import { cn } from '$lib/utils';

const CHAT_CHANNELS_TABLE_GRID_TEMPLATE =
  'grid grid-cols-[72px_minmax(0,1fr)_90px_minmax(0,1.1fr)_minmax(0,1fr)_160px_150px] gap-3';

export const chatChannelsTableHeaderRowClass = cn(
  CHAT_CHANNELS_TABLE_GRID_TEMPLATE,
  'bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground'
);

export const chatChannelsTableDataRowClass = cn(
  CHAT_CHANNELS_TABLE_GRID_TEMPLATE,
  'min-h-16 border-t px-3 py-3'
);
