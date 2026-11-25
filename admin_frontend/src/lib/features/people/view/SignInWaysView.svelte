<script lang="ts">
  // People → Sign-in: the ways into HiroLeague and its apps (trust fixes). Name and password always work; "Sign in
  // with Home Assistant" is an option the owner adds, run by the core itself: it can be turned on only once the core
  // reaches Home Assistant, and only a Home Assistant login linked to someone in the family list signs in.
  // Pieces: the kit's Panel, Field, Feedback, StatusDot, PickSelect, ResourceView; shadcn-svelte's Switch, Input,
  // Table, Badge.
  import { House, KeyRound, PlugZap, Unplug } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import { Input } from '$kit/components/ui/input/index.js';
  import { Switch } from '$kit/components/ui/switch/index.js';
  import * as Table from '$kit/components/ui/table/index.js';
  import Feedback from '$kit/ui/feedback.svelte';
  import Field from '$kit/ui/field.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import { dateTime } from '$kit/format/time';
  import type { HomeAssistantSignIn } from '../state/home-assistant-sign-in.svelte';

  interface Props {
    ha: HomeAssistantSignIn;
    /** The family list, for who each Home Assistant login is. */
    family: { person_id: string; name: string }[];
  }
  let { ha, family }: Props = $props();
  const uid = $props.id();

  const ROW = 'flex items-center justify-between gap-4 px-3 py-3';
  const options = $derived([{ value: '', label: 'Nobody' }, ...family.map((p) => ({ value: p.person_id, label: p.name }))]);
  const state = $derived(ha.data);
</script>

<div class="grid gap-4">
  <Feedback error={ha.error ?? ''} />
  <Panel title="Ways to sign in">
    <ul class="divide-y rounded-md border">
      <li class={ROW}>
        <span class="flex items-center gap-2 text-sm"><KeyRound size={15} class="text-muted-foreground" /> Name and password</span>
        <Badge variant="secondary">Always on</Badge>
      </li>
      <li class={ROW}>
        <span class="grid gap-0.5">
          <span class="flex items-center gap-2 text-sm"><House size={15} class="text-muted-foreground" /> Home Assistant</span>
          <span class="text-xs text-muted-foreground">
            {#if !ha.canTurnOn}
              Connect Home Assistant below first
            {:else if state?.enabled}
              On the sign-in page, for the {ha.linkedCount} linked {ha.linkedCount === 1 ? 'login' : 'logins'}
            {:else}
              Off
            {/if}
          </span>
        </span>
        <Switch
          checked={!!state?.enabled}
          disabled={!ha.canTurnOn || ha.switching.busy}
          onCheckedChange={(next) => void ha.setOn(next)}
          aria-label="Sign in with Home Assistant: {state?.enabled ? 'on' : 'off'}"
          title={ha.canTurnOn ? '' : 'Connect Home Assistant first'}
        />
      </li>
    </ul>
    <Feedback action={ha.switching} />
  </Panel>

  <Panel title="Home Assistant">
    {#snippet actions()}
      {#if state?.connected}
        <span class="flex items-center gap-2 text-sm" title={state.checked_at ? `Tested ${dateTime(state.checked_at)}` : ''}>
          <StatusDot tone="ok" /> Connected, Home Assistant {state.version}
        </span>
      {:else}
        <span class="flex items-center gap-2 text-sm text-muted-foreground"><StatusDot tone="off" /> Not connected</span>
      {/if}
    {/snippet}
    <div class="grid max-w-xl gap-4">
      <Field label="Address" for="{uid}-address">
        <Input id="{uid}-address" bind:value={ha.form.value.address} placeholder="http://homeassistant.local" spellcheck="false" />
      </Field>
      <Field
        label="Access token"
        for="{uid}-token"
        hint={state?.token_set ? 'Kept. Type a new one to replace it.' : 'A long-lived token, made in your Home Assistant profile'}
      >
        <Input id="{uid}-token" bind:value={ha.form.value.token} type="password" autocomplete="off" />
      </Field>
      <div class="flex gap-2">
        <Button disabled={!ha.canConnect} onclick={() => void ha.connect()}>
          <PlugZap size={15} /> {state?.connected ? 'Test again' : 'Connect'}
        </Button>
        {#if state?.connected || state?.token_set}
          <Button variant="ghost" disabled={ha.disconnecting.busy} onclick={() => void ha.disconnect()}>
            <Unplug size={15} /> Disconnect
          </Button>
        {/if}
      </div>
      <Feedback action={ha.form.action} />
      <Feedback action={ha.disconnecting} />
    </div>
  </Panel>

  {#if state?.connected && state.logins.length}
    <Panel title="Who is who">
      <Table.Root>
        <Table.Header>
          <Table.Row>
            <Table.Head>In Home Assistant</Table.Head>
            <Table.Head>Login</Table.Head>
            <Table.Head class="w-64">In the family list</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each state.logins as login (login.ha_user_id)}
            <Table.Row>
              <Table.Cell>{login.name}</Table.Cell>
              <Table.Cell class="font-mono text-xs text-muted-foreground">{login.login || '—'}</Table.Cell>
              <Table.Cell>
                <PickSelect
                  value={login.person_id}
                  {options}
                  disabled={ha.linking.busy(login.ha_user_id)}
                  onchange={(v) => void ha.link(login.ha_user_id, v)}
                  label="Who {login.name} is in the family list"
                />
                {#if ha.linking.error(login.ha_user_id)}
                  <p class="mt-1 text-xs text-destructive">{ha.linking.error(login.ha_user_id)}</p>
                {/if}
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </Panel>
  {/if}
</div>
