<script lang="ts">
	// One LLM request, opened: what was sent (the pictures, the words by where each part came from, and the answer's
	// shape), what came back (the reply laid out, as it came, and what the app did with it), and the details (each
	// model asked, detail level, time, tokens, cost). Nothing here knows a kind: the asker labels its parts, and
	// shape.ts reads any schema and reply.
	import { LOGS } from '$hiro-app/logs';
	import Notice from '$kit/ui/notice.svelte';
	import { resolve } from '$app/paths';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Tabs from '$kit/components/ui/tabs/index.js';
	import ResourceView from '$kit/ui/resource-view.svelte';
	import { getLlmRequest, llmPictureUrl } from '../api';
	import { Resource } from '$kit/state/resource.svelte';
	import { fullDateTime } from '$kit/format/time';
	import { usd } from '$kit/format/money';
	import { count } from '$kit/format/number';
	import { ArrowRight, Check, Copy, Maximize2, Minimize2, X } from '@lucide/svelte';
	import { parsed, pretty, shape } from './shape';

	let { id }: { id: string } = $props();
	const data = new Resource((signal) => getLlmRequest(id, signal));
	const r = $derived(data.data);
	let tab = $state<'sent' | 'back' | 'details'>('sent');
	let big = $state<number | null>(null); // the picture shown full width
	let raw = $state(false);
	let copied = $state(false);

	const copy = async () => {
		if (!r) return;
		await navigator.clipboard.writeText(r.prompt);
		copied = true;
		setTimeout(() => (copied = false), 1500);
	};
	const href = (to: string) => {
		const [path, query] = to.split('?');
		return resolve(path as '/') + (query ? `?${query}` : '');
	};
	const answer = $derived(r ? parsed(r.reply ?? '') : null);
	const rows = $derived(r ? shape(r.answer_schema) : []);
	const kb = (bytes: number) => `${Math.round(bytes / 1000)} kB`;
	const openLabel = (source: string) => LOGS.llm?.openLabel(source) ?? 'the question';
</script>

<!-- any reply, laid out: parts as name/value rows, lists as numbered boxes -->
{#snippet show(v: unknown)}
	{#if Array.isArray(v)}
		{#if v.length}
			<div class="grid gap-1.5">
				{#each v as item, n (n)}
					<div class="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-1 rounded-md border px-2 py-1.5">
						<span class="text-xs text-muted-foreground">{n + 1}.</span>
						{@render show(item)}
					</div>
				{/each}
			</div>
		{:else}
			<span class="text-muted-foreground">none</span>
		{/if}
	{:else if v !== null && typeof v === 'object'}
		<div class="grid gap-x-3 gap-y-1 text-sm sm:grid-cols-[7rem_minmax(0,1fr)]">
			{#each Object.entries(v) as [k, x] (k)}
				<span class="text-xs text-muted-foreground sm:pt-0.5">{k}</span>
				<div class="min-w-0">{@render show(x)}</div>
			{/each}
		</div>
	{:else}
		<span class="font-medium">{String(v)}</span>
	{/if}
{/snippet}

<div class="grid gap-3 rounded-md border p-3">
	<ResourceView resource={data} errorTitle="Could not load this request">
		{#snippet children(r)}
				<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
					<span class="font-medium">{r.task}</span>
					<span class="text-xs text-muted-foreground">{r.source}{r.camera ? ` · ${r.camera}` : ''} · {fullDateTime(r.at)}</span>
					{#if r.link}<a class="ml-auto inline-flex items-center gap-1 text-xs underline" href={href(r.link)}>Open {openLabel(r.source)} <ArrowRight class="size-3" /></a>{/if}
				</div>
				{#if r.error}<Notice tone="error" message={r.error} />{/if}
				{#if r.warning}<Notice tone="warning" message={r.warning} />{/if}

				<Tabs.Root bind:value={tab}>
					<Tabs.List>
						<Tabs.Trigger value="sent">What was sent</Tabs.Trigger>
						<Tabs.Trigger value="back">What came back</Tabs.Trigger>
						<Tabs.Trigger value="details">Details</Tabs.Trigger>
					</Tabs.List>

					<Tabs.Content value="sent" class="grid gap-4 pt-2">
						<!-- the pictures, and what came back laid out beside them (below when a picture is full width) -->
						<div class="flex flex-wrap items-start gap-4">
							<div class="grid min-w-0 gap-4 {big !== null ? 'basis-full' : ''}">
								{#each r.pictures as pic, n (n)}
									<figure class="grid gap-1">
										{#if r.pictures_kept}
											<div class="relative">
												<img src={llmPictureUrl(r.id, n)} alt={pic.label} class="rounded-md border {big === n ? 'w-full' : 'max-h-80 w-auto'}" />
												<button
													class="absolute top-1.5 right-1.5 rounded bg-black/60 p-1 text-white"
													title={big === n ? 'Smaller' : 'Full width'}
													onclick={() => (big = big === n ? null : n)}
												>
													{#if big === n}<Minimize2 class="size-4" />{:else}<Maximize2 class="size-4" />{/if}
												</button>
											</div>
										{:else}
											<p class="rounded-md border border-dashed px-2 py-3 text-xs text-muted-foreground">Not kept any more: pictures are kept for fewer days than the words.</p>
										{/if}
										<figcaption class="text-[11px] text-muted-foreground">
											{#if r.pictures.length > 1}<span class="font-medium text-foreground">Picture {n + 1} of {r.pictures.length}:</span>{/if}
											{pic.label} · exactly as sent · {pic.width} × {pic.height} px · {kb(pic.size)}{r.detail ? ` · ${r.detail} detail` : ''}
										</figcaption>
									</figure>
								{:else}
									<p class="text-xs text-muted-foreground">Words only: no picture.</p>
								{/each}
							</div>
							{#if answer !== null}
								<div class="grid min-w-56 flex-1 content-start gap-1.5">
									<span class="font-medium">What came back</span>
									{@render show(answer)}
								</div>
							{:else if r.error}
								<p class="min-w-56 flex-1 text-xs text-destructive">No answer: {r.error}</p>
							{/if}
						</div>

						<div class="grid gap-1.5">
							<div class="flex flex-wrap items-center gap-2">
								<span class="font-medium">The words</span>
								<span class="text-xs text-muted-foreground">each part says where it came from: change it there</span>
								<Button size="sm" variant="ghost" class="ml-auto h-7" onclick={copy}>{#if copied}<Check />{:else}<Copy />{/if} Copy</Button>
								<Button variant="link" size="sm" onclick={() => (raw = !raw)}>{raw ? 'By part' : 'Exactly as sent'}</Button>
							</div>
							{#if raw}
								<pre class="max-h-96 overflow-auto rounded-md border bg-muted/40 p-2 font-mono text-[11px] whitespace-pre-wrap">{r.prompt}

		{JSON.stringify(r.answer_schema, null, 2)}</pre>
							{:else}
								<div class="grid gap-1.5">
									{#each r.parts as p, n (n)}
										<div
											class="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-3 rounded-md border-l-4 bg-muted/30 py-1.5 pr-2 pl-2 text-sm max-sm:grid-cols-1 {p.link
												? 'border-l-primary/60'
												: 'border-l-muted-foreground/30'}"
										>
											<span class="text-[11px] text-muted-foreground">
												{#if p.link}<a class="underline" href={href(p.link)}>{p.label}</a>{:else}{p.label}{/if}
											</span>
											<span class="whitespace-pre-wrap">{p.text}</span>
										</div>
									{/each}
								</div>
							{/if}
						</div>

						{#if rows.length}
							<div class="grid gap-1.5">
								<span class="font-medium">The answer it had to give <span class="text-xs font-normal text-muted-foreground">(the model can reply only in this shape)</span></span>
								<div class="grid gap-x-3 gap-y-0.5 rounded-md border px-2 py-1.5 text-xs sm:grid-cols-[8rem_minmax(0,1fr)]">
									{#each rows as f, n (n)}
										<span class="font-mono" style="padding-left: {f.depth}rem">{f.depth ? '· ' : ''}{f.path}</span><span class="text-muted-foreground">{f.allowed}</span>
									{/each}
								</div>
							</div>
						{/if}
					</Tabs.Content>

					<Tabs.Content value="back" class="grid gap-4 pt-2">
						{#if answer !== null}
							<div class="grid gap-1.5">
								<span class="font-medium">The answer</span>
								{@render show(answer)}
							</div>
						{/if}
						{#if r.reply}
							<div class="grid gap-1">
								<span class="text-xs font-medium">The model's reply, as it came{answer !== null ? ' (laid out)' : ''}</span>
								<pre class="max-h-80 overflow-auto rounded-md border bg-muted/40 p-2 font-mono text-[11px] whitespace-pre-wrap">{pretty(r.reply)}</pre>
							</div>
						{:else}
							<p class="text-sm text-muted-foreground">No reply.</p>
						{/if}
						{#if r.outcome}<p class="text-xs text-muted-foreground"><span class="font-medium text-foreground">What {LOGS.name} did:</span> {r.outcome}</p>{/if}
					</Tabs.Content>

					<Tabs.Content value="details" class="grid gap-4 pt-2 text-sm">
						<div class="grid gap-1.5">
							<span class="font-medium">Who was asked</span>
							{#each r.tries as t, n (n)}
								<div class="flex flex-wrap items-center gap-2 text-xs">
									<span class="w-4 text-muted-foreground">{n + 1}.</span>
									{#if t.ok}<Check class="size-4 text-success" />{:else}<X class="size-4 text-destructive" />{/if}
									<span class="font-medium">{t.profile ?? t.provider ?? '?'}</span>
									<span class="text-muted-foreground"
										>{[t.profile ? t.provider : null, t.model].filter(Boolean).join(' · ')}{t.model ? ' · ' : ''}{t.outcome}{t.ms ? ` · ${(t.ms / 1000).toFixed(1)} s` : ''}</span
									>
								</div>
							{/each}
						</div>
						<div class="grid gap-x-3 gap-y-1 text-xs sm:grid-cols-[9rem_minmax(0,1fr)]">
							<span class="text-muted-foreground">Answered by</span><span>{r.profile ? `${r.profile} · ` : ''}{r.provider ?? '?'} · {r.model ?? '?'}</span>
							{#if r.detail}<span class="text-muted-foreground">Picture detail</span><span>{r.detail}</span>{/if}
							{#if r.thinking}<span class="text-muted-foreground">Thinking</span><span>{r.thinking}</span>{/if}
							<span class="text-muted-foreground">Took</span><span>{(r.ms / 1000).toFixed(1)} s</span>
							<span class="text-muted-foreground">Tokens</span><span>{count(r.tokens_in)} in · {count(r.tokens_out)} out</span>
							<span class="text-muted-foreground">Cost</span><span>{r.cost === null ? 'no price: on your plan, or a model without one' : `about ${usd(r.cost)}`}</span>
						</div>
					</Tabs.Content>
				</Tabs.Root>
		{/snippet}
	</ResourceView>
</div>
