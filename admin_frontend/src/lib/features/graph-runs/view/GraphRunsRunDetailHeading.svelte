<script lang="ts">
  import type { CharacterDetail } from '$lib/api/characters';
  import type { GraphLedgerRow } from '$lib/api/graph-runs';
  import {
    adminLogsUrlForInboundId,
    runStatusDataValue,
    type ActivePane
  } from '../graph-runs-pure';

  let {
    activePane,
    activeRunAggregate,
    langsmithUrlForActive,
    runIdentitySource,
    titleCharacter,
    runTitlePrimary,
    runTitleSubtitle,
    runIdFirstCardDisplay
  }: {
    activePane: ActivePane;
    activeRunAggregate: GraphLedgerRow | null;
    langsmithUrlForActive: string | null;
    runIdentitySource: GraphLedgerRow | null;
    titleCharacter: CharacterDetail | null;
    runTitlePrimary: string;
    runTitleSubtitle: string;
    runIdFirstCardDisplay: string;
  } = $props();
</script>

<div class="run-detail-toolbar">
  <div class="run-toolbar-lead">
    <span
      class="run-status-dot"
      data-status={runStatusDataValue(activeRunAggregate?.status ?? '')}
      title={activeRunAggregate?.status ? `Status: ${activeRunAggregate.status}` : 'No aggregate row yet'}
      aria-label={activeRunAggregate?.status ? `Run status: ${activeRunAggregate.status}` : 'Run status unknown'}
    ></span>
    {#if titleCharacter?.photo_data_url}
      <img
        class="run-title-avatar"
        src={titleCharacter.photo_data_url}
        alt=""
        width="40"
        height="40"
      />
    {:else}
      <div class="run-title-avatar run-title-avatar--placeholder" aria-hidden="true"></div>
    {/if}
    <div class="run-title-block">
      <div class="run-title-top">
        <h2 class="run-detail-title">{runTitlePrimary}</h2>
        {#if langsmithUrlForActive}
          <a
            class="title-langsmith-link"
            href={langsmithUrlForActive}
            target="_blank"
            rel="noreferrer"
            title="LangSmith graph trace"
            >LangSmith</a
          >
        {/if}
        {#if String(runIdentitySource?.inbound_id ?? '').trim()}
          <a
            class="title-langsmith-link"
            href={adminLogsUrlForInboundId(String(runIdentitySource?.inbound_id ?? ''))}
            title="Operational logs filtered to this inbound id (msg_id)"
            >Logs</a
          >
        {/if}
      </div>
      {#if runTitleSubtitle}
        <p class="run-title-sub">Channel: {runTitleSubtitle}</p>
      {/if}
      <p class="run-title-runid mono" title={activePane}>{runIdFirstCardDisplay}</p>
    </div>
  </div>
</div>

<style>
  .run-detail-toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    gap: 12px 16px;
    padding: 10px 12px;
    border: 1px solid var(--border, #d4d4d8);
    border-radius: 8px;
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 5%, transparent);
    min-width: 0;
    align-self: stretch;
    box-sizing: border-box;
  }

  .run-toolbar-lead {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    flex: 0 1 340px;
    min-width: 0;
  }

  .run-title-avatar {
    width: 40px;
    height: 40px;
    border-radius: 999px;
    object-fit: cover;
    flex-shrink: 0;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, #000 10%, transparent);
  }

  .run-title-avatar--placeholder {
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 18%, transparent);
  }

  .run-title-block {
    min-width: 0;
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .run-title-top {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 8px 14px;
    min-width: 0;
  }

  .run-title-sub {
    margin: 0;
    font-size: 13px;
    line-height: 1.3;
    color: var(--muted-foreground, #64748b);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .run-title-runid {
    margin: 0;
    font-size: 11px;
    line-height: 1.3;
    color: var(--muted-foreground, #64748b);
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-all;
  }

  .title-langsmith-link {
    flex-shrink: 0;
    border: 1px solid var(--border, #d4d4d8);
    border-radius: 6px;
    color: var(--primary, #0369a1);
    font-size: 12px;
    padding: 4px 8px;
    text-decoration: none;
    white-space: nowrap;
  }

  .title-langsmith-link:hover {
    background: color-mix(in srgb, var(--primary, #0369a1) 8%, transparent);
  }

  .run-status-dot {
    width: 11px;
    height: 11px;
    border-radius: 999px;
    flex-shrink: 0;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, #000 12%, transparent);
  }

  .run-status-dot[data-status='completed'] {
    background: #22c55e;
  }

  .run-status-dot[data-status='failed'] {
    background: #ef4444;
  }

  .run-status-dot[data-status='cancelled'] {
    background: #f97316;
  }

  .run-status-dot[data-status='skipped'] {
    background: #a855f7;
  }

  .run-status-dot[data-status='unknown'] {
    background: #94a3b8;
  }

  .run-status-dot[data-status='other'] {
    background: #3b82f6;
  }

  .run-detail-title {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    line-height: 1.2;
    font-family: inherit;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mono {
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  }
</style>
