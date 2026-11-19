<script lang="ts">
	// Where the lines come from: one file a day in DATA_DIR/logs (kept a set number of days) and the crash
	// file, each with a download for sending it on.
	import { getLogFiles, logFileUrl } from './api';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Table from '$kit/components/ui/table/index.js';
	import { Resource } from '$kit/state/resource.svelte';
	import ResourceView from '$kit/ui/resource-view.svelte';
	import { bytes } from '$kit/format/number';
	import { day, dayOf } from '$kit/format/time';
	import { Download } from '@lucide/svelte';

	const files = new Resource((signal) => getLogFiles(signal), { on: ['logs'], every: 60_000 });
	const size = (b: number) => (b ? bytes(b) : 'empty');
	const dayWords = (iso: string) => day(dayOf(iso)); // "Today", "Mon, Sep 28"
</script>

<details class="rounded-md border px-3 py-2 text-sm">
	<summary class="cursor-pointer text-muted-foreground">
		Log files · DATA_DIR/logs (one a day, kept across restarts and deploys{files.data ? `, ${files.data.keep_days} days` : ''})
	</summary>
	<div class="mt-2">
		<ResourceView resource={files} quiet errorTitle="Could not load the log files">
			{#snippet children(got)}
				<Table.Root compact>
					<Table.Header>
						<Table.Row>
							<Table.Head class="font-normal text-muted-foreground">File</Table.Head>
							<Table.Head class="font-normal text-muted-foreground">What</Table.Head>
							<Table.Head class="font-normal text-muted-foreground">Size</Table.Head>
							<Table.Head></Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each got.files as f (f.name)}
							<Table.Row>
								<Table.Cell class="font-mono">{f.name}</Table.Cell>
								<Table.Cell class="whitespace-normal text-muted-foreground">{f.day ? `${dayWords(f.day)}: ${f.what}` : f.what}</Table.Cell>
								<Table.Cell class="tabular-nums">{size(f.size)}</Table.Cell>
								<Table.Cell class="text-right">
									<Button size="xs" variant="ghost" href={f.size ? logFileUrl(f.name) : undefined} disabled={!f.size} download><Download /> Download</Button>
								</Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			{/snippet}
		</ResourceView>
	</div>
</details>
