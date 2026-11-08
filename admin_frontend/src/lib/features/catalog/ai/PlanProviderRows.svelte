<script lang="ts">
  /**
   * Claude Code and Codex as rows of the Providers list (catalog hosting "plan": signed in with the
   * owner's plan instead of an API key). The page asks `ProvidersTab` to skip the catalog's own rows
   * for them and draws these with the live status (`GET /api/ai/plans`). The action opens the plan
   * dialog (sign in / out, update, test question).
   */
  import { humanDateTime } from '$lib/format/human-datetime';
  import AiProviderRow from './AiProviderRow.svelte';
  import type { AiController } from './ai-controller.svelte';
  import { planToolInfo, planToolStatus } from './ai-profile-rules';

  let { ai, activeOnly }: { ai: AiController; activeOnly: boolean } = $props();

  const rows = $derived(activeOnly ? ai.plans.filter((t) => t.signed_in) : ai.plans);
</script>

{#each rows as tool (tool.id)}
  <AiProviderRow
    name={tool.name}
    id={tool.id}
    status={planToolStatus(tool)}
    hosting="plan"
    auth="plan sign-in"
    models={tool.models.length}
    kinds="chat"
    recommended={tool.models[0] ? { kind: 'chat', name: tool.models[0].name, id: `${tool.id}:${tool.models[0].id}` } : null}
    updated={ai.planUpdates?.last_run ? humanDateTime(ai.planUpdates.last_run) : '-'}
    info={planToolInfo(tool, ai.planUpdates, ai.profilesOnProvider(tool.id))}
    actionLabel="Manage"
    onAction={() => ai.openProviderDialog(tool.id)}
  />
{/each}
