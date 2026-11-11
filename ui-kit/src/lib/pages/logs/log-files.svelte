<script lang="ts">
	// Where the lines come from: the files in DATA_DIR/logs, how full each is before it rotates, and a
	// download for sending one on (older copies too).
	import { getLogFiles, logFileUrl } from './api';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Table from '$kit/components/ui/table/index.js';
	import { Resource } from '$kit/state/resource.svelte';
	import ResourceView from '$kit/ui/resource-view.svelte';
	import { bytes } from '$kit/format/number';
	import { Download } from '@lucide/svelte';

	const files = new Resource((signal) => getLogFiles(signal), { on: ['logs'], every: 60_000 });
	const size = (b: number) => (b ? bytes(b) : 'empty');
</script>

<details class="rounded-md border px-3 py-2 text-sm">
	<summary class="cursor-pointer text-muted-foreground">Log files · DATA_DIR/logs (kept across restarts and deploys)</summary>
	<div class="mt-2">
		<ResourceView resource={files} quiet errorTitle="Could not load the log files">
			{#snippet children(list)}
				<Table.Root compact>
					<Table.Header>
						<Table.Row>
							<Table.Head class="font-normal text-muted-foreground">File</Table.Head>
							<Table.Head class="font-normal text-muted-foreground">What</Table.Head>
							<Table.Head class="font-normal text-muted-foreground">Size</Table.Head>
							<Table.Head class="font-normal text-muted-foreground">Older copies</Table.Head>
							<Table.Head></Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each list as f (f.name)}
							<Table.Row>
								<Table.Cell class="font-mono">{f.name}</Table.Cell>
								<Table.Cell class="whitespace-normal text-muted-foreground">{f.what}</Table.Cell>
								<Table.Cell class="tabular-nums">{size(f.size)}{f.limit ? ` of ${size(f.limit)}` : ''}</Table.Cell>
								<Table.Cell class="tabular-nums">
									{#if f.keep}
										{f.kept} of {f.keep}
										{#each Array.from({ length: f.kept }, (_, i) => i + 1) as n (n)}
											<a class="ml-1 underline decoration-dotted" href={logFileUrl(`${f.name}.${n}`)} download title="Download {f.name}.{n}">.{n}</a>
										{/each}
									{:else}—{/if}
								</Table.Cell>
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
