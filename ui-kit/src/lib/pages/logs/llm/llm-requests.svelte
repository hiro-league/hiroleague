<script lang="ts">
	// Logs → LLM requests: every question the app sent to an LLM, newest first; one opened beside the list with what was sent, what came back and
	// the details. New requests appear as they're kept (notice "llm"). Backend: llm/recorder.py, llm/requests_api.py.
	import { LOGS } from '$hiro-app/logs';
	import Loading from '$kit/ui/loading.svelte';
	import EmptyState from '$kit/ui/empty-state.svelte';
	import { Input } from '$kit/components/ui/input/index.js';
	import { Switch } from '$kit/components/ui/switch/index.js';
	import { getLlmRequests, llmPictureUrl, type LlmRequestRow } from '../api';
	import { Resource } from '$kit/state/resource.svelte';
	import { dateTime, fullDateTime } from '$kit/format/time';
	import { usd } from '$kit/format/money';
	import { bytes } from '$kit/format/number';
	import Segmented from '$kit/ui/segmented.svelte';
	import StickyBar from '$kit/ui/sticky-bar.svelte';
	import { oneLine } from './shape';
	import LlmRequestView from './llm-request.svelte';

	const llm = LOGS.llm;
	const FROM = [{ value: 'all', label: 'All' }, ...(llm?.askers ?? []).map((a) => ({ value: a, label: a }))];
	let source = $state('all');
	let camera = $state('all');
	let problems = $state(false);
	let typed = $state('');
	let q = $state(''); // `typed`, once typing pauses
	let openId = $state<string | null>(null);

	$effect(() => {
		const t = typed;
		const timer = setTimeout(() => (q = t), 300);
		return () => clearTimeout(timer);
	});
	const list = new Resource((signal) => getLlmRequests({ source, camera, problems, q }, signal), { on: ['llm'], debounce: 500 });
	const shown = $derived(list.data?.requests ?? []);
	const open = $derived(shown.find((r) => r.id === openId) ?? shown[0]);

	const short = (r: LlmRequestRow) => (r.status === 'failed' ? (r.error ?? 'failed') : oneLine(r.reply ?? ''));
	const tone = (r: LlmRequestRow) => (r.status === 'failed' ? 'text-destructive' : r.status === 'fell back' || r.warning ? 'text-warning' : 'text-muted-foreground');
</script>

<div class="grid gap-3">
	<StickyBar class="flex flex-wrap items-center gap-x-4 gap-y-2 bg-background">
		<Segmented options={FROM} value={source} onchange={(v) => (source = v)} label="Asked by" />
		{#if list.data?.cameras.length}
			<Segmented
				options={[{ value: 'all', label: 'All cameras' }, ...list.data.cameras.map((c) => ({ value: c, label: c }))]}
				value={camera}
				onchange={(v) => (camera = v)}
				label="Camera"
			/>
		{/if}
		<label class="flex items-center gap-2 text-xs"><Switch bind:checked={problems} /> Problems only</label>
		<Input class="h-8 w-56" bind:value={typed} placeholder="Search words, replies, cameras…" />
		{#if list.data}
			<span class="ml-auto text-xs text-muted-foreground">
				Kept {list.data.keep_days} days · pictures {list.data.picture_days} days · {bytes(list.data.disk)}
			</span>
		{/if}
	</StickyBar>

	{#if list.error}<p class="text-sm text-destructive">{list.error}</p>{/if}
	{#if list.data?.more}<p class="text-xs text-muted-foreground">Only the newest {shown.length} are shown: pick what asked, or search.</p>{/if}
	<div class="grid items-start gap-3 lg:grid-cols-[24rem_minmax(0,1fr)]">
		<div class="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1 lg:max-h-[calc(100vh-14rem)] lg:overflow-x-hidden lg:overflow-y-auto">
			{#each shown as r (r.id)}
				<button
					class="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-2.5 rounded-md border p-2 text-left text-sm hover:bg-muted/50 {open?.id === r.id ? 'border-primary bg-muted/50' : ''}"
					onclick={() => (openId = r.id)}
				>
					{#if r.pictures && r.pictures_kept}
						<span class="relative">
							<img src={llmPictureUrl(r.id, 0)} alt="" class="h-12 w-18 rounded object-cover object-left-top" loading="lazy" />
							{#if r.pictures > 1}<span class="absolute right-0.5 bottom-0.5 rounded bg-black/70 px-1 text-[10px] text-white">+{r.pictures - 1}</span>{/if}
						</span>
					{:else}
						<span class="flex h-12 w-18 items-center justify-center rounded bg-muted text-center text-[10px] text-muted-foreground"
							>{r.pictures ? 'picture gone' : 'words only'}</span
						>
					{/if}
					<span class="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-0.5">
						<span class="flex items-baseline gap-2">
							<span class="min-w-0 truncate font-medium">{r.task}</span>
							<span class="ml-auto shrink-0 text-[11px] text-muted-foreground" title={fullDateTime(r.at)}>{dateTime(r.at)}</span>
						</span>
						<span class="truncate text-xs {tone(r)}">{short(r)}</span>
						<span class="truncate text-[11px] text-muted-foreground"
							>{r.source} · {r.model ?? '?'} · {(r.ms / 1000).toFixed(1)} s · {r.cost === null ? 'no price (a plan)' : usd(r.cost)}{#if r.status !== 'ok'}
								· <span class={tone(r)}>{r.status}</span>{/if}</span
						>
					</span>
				</button>
			{:else}
				{#if list.loading || !list.data}
					<Loading class="py-2" />
				{:else}
					<EmptyState message={typed || problems || source !== 'all' || camera !== 'all' ? 'Nothing matches.' : 'No questions sent to an LLM yet.'} />
				{/if}
			{/each}
		</div>
		{#if open}
			{#key open.id}<LlmRequestView id={open.id} />{/key}
		{/if}
	</div>
</div>
