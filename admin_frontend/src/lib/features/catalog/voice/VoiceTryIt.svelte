<script lang="ts">
  /**
   * Try it, beside the voice profile editor (Phase 7b), as HomeHiro's "Speak with a voice" did: speak a
   * text with the profile as it is in the editor (saved or not) or with another saved profile; Gemini's
   * sound tags (the common ones, or all by group) go in at the cursor; the takes pile up newest first to
   * compare voices, each with its length, size, time and cost (exact from Gemini's usage, estimated for
   * OpenAI), to play, download (.ogg) or send to a family member as a WhatsApp voice note. Each take is a
   * paid call, counted in AI usage under Hiro → Try it.
   */
  import { tick } from 'svelte';
  import { Download, Loader, Send } from '@lucide/svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import type { Person } from '$lib/api/people';
  import {
    sendVoiceClip,
    tryVoice,
    voiceClipUrl,
    type VoiceCatalog,
    type VoiceClip,
    type VoiceProfileFields,
    type VoiceProfileRow
  } from '$lib/api/voice';
  import { ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import { hasTags, money, withTag } from './voice-format';

  let {
    editing,
    profiles,
    catalog,
    people
  }: {
    /** The profile in the editor, as it is now. */
    editing: { id: string | null; fields: VoiceProfileFields; dirty: boolean };
    profiles: VoiceProfileRow[];
    catalog: VoiceCatalog | null;
    people: Person[];
  } = $props();

  type Take = { clip: VoiceClip; profile: string; provider: string; text: string; note?: string; sending?: boolean };

  let tryWith = $state(''); // '' = the editor's profile
  let text = $state('Someone is at the front door. <short pause> It looks like the delivery guy.');
  let allTags = $state(false);
  let sendTo = $state('');
  let takes = $state<Take[]>([]);
  let generating = $state(false);
  let error = $state<string | null>(null);
  let textEl = $state<HTMLTextAreaElement | null>(null);

  const maxChars = $derived(catalog?.max_chars ?? 4096);
  const others = $derived(profiles.filter((p) => p.id !== editing.id));
  const picked = $derived(others.find((p) => p.id === tryWith));
  const provider = (model: string) => (model.startsWith('openai:') ? 'OpenAI' : 'Google');
  const speaker = $derived(
    picked
      ? { name: picked.label, provider: provider(picked.model), voice: picked.voice_label || picked.voice }
      : { name: editing.fields.label, provider: provider(editing.fields.model), voice: editing.fields.voice_label || editing.fields.voice }
  );
  const gemini = $derived(speaker.provider === 'Google');
  const editingLabel = $derived(
    `${editing.fields.label || 'New profile'}, as it is in the editor${editing.dirty || !editing.id ? ' (not saved)' : ''}`
  );
  const tooLong = $derived(text.length > maxChars);
  const shownTags = $derived(allTags ? [] : (catalog?.common_tags ?? []));
  const spent = $derived(takes.reduce((s, t) => s + (t.clip.cost_usd ?? 0), 0));
  const recipient = $derived(people.find((p) => p.person_id === sendTo) ?? people[0]);

  async function insertTag(tag: string) {
    const start = textEl?.selectionStart ?? text.length;
    const r = withTag(text, start, textEl?.selectionEnd ?? start, tag);
    text = r.text;
    await tick();
    textEl?.focus();
    textEl?.setSelectionRange(r.at, r.at);
  }

  async function generate() {
    generating = true;
    const said = text;
    const res = picked ? await tryVoice({ text: said, profile_id: picked.id }) : await tryVoice({ text: said, draft: editing.fields });
    generating = false;
    if (!res.ok || !res.data) {
      error = res.error ?? 'Nothing was spoken.';
      return;
    }
    error = null;
    takes = [{ clip: res.data.clip, profile: speaker.name, provider: speaker.provider, text: said }, ...takes];
  }

  async function send(t: Take) {
    if (!recipient) return;
    t.sending = true;
    const res = await sendVoiceClip(t.clip.id, recipient.person_id);
    t.sending = false;
    t.note = res.ok ? `Sent to ${res.data?.name ?? recipient.name} as a voice note.` : `Not sent: ${res.error ?? 'unknown error'}`;
  }

  const tagBtn = 'rounded-md border px-1.5 py-0.5 font-mono text-[11px] hover:bg-accent disabled:opacity-50';
</script>

<SectionCardMuted title="Try it">
  <div class="grid gap-3">
    <label class="grid gap-1 text-xs text-muted-foreground">
      Speak with
      <select class={ADMIN_SELECT} bind:value={tryWith}>
        <option value="">{editingLabel}</option>
        {#each others as p (p.id)}<option value={p.id}>{p.label}</option>{/each}
      </select>
    </label>
    <p class="-mt-2 text-xs text-muted-foreground">{speaker.provider} · {speaker.voice || 'no voice picked'}</p>

    <textarea rows="3" bind:this={textEl} bind:value={text} placeholder="Type something to say"></textarea>

    <div class="grid gap-1.5">
      <div class="flex flex-wrap items-center gap-1">
        <span class="mr-1 text-xs text-muted-foreground">Sound tags</span>
        {#each shownTags as t (t)}
          <button type="button" class={tagBtn} disabled={!gemini} onclick={() => insertTag(t)}>{t}</button>
        {/each}
        <button
          type="button"
          class="px-1 text-xs text-primary hover:underline disabled:opacity-50"
          disabled={!gemini}
          onclick={() => (allTags = !allTags)}>{allTags ? 'Fewer' : 'All tags…'}</button
        >
      </div>
      {#if allTags && gemini}
        <div class="grid gap-1.5 rounded-md border bg-background p-2">
          {#each Object.entries(catalog?.tag_groups ?? {}) as [group, tags] (group)}
            <div class="flex flex-wrap items-center gap-1">
              <span class="w-16 text-xs text-muted-foreground">{group}</span>
              {#each tags as t (t)}<button type="button" class={tagBtn} onclick={() => insertTag(t)}>{t}</button>{/each}
            </div>
          {/each}
        </div>
      {/if}
      <p class="text-xs text-muted-foreground">
        {#if gemini}
          Inserted where the cursor is. Gemini makes the sound at that point; keep tags in English even in other languages.
        {:else if hasTags(text)}
          OpenAI has no sound tags: the tags in this text are removed before it is spoken.
        {:else}
          Sound tags work with Gemini 3.8 only.
        {/if}
      </p>
    </div>

    <div class="flex flex-wrap items-center gap-3">
      <Button onclick={generate} disabled={!text.trim() || tooLong || generating || !speaker.voice}>
        {#if generating}<Loader size={14} class="animate-spin" /> Speaking…{:else}Generate{/if}
      </Button>
      <span class={cn('text-xs', tooLong ? 'text-destructive' : 'text-muted-foreground')}>{text.length} of {maxChars} characters</span>
      {#if people.length}
        <label class="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          WhatsApp to
          <select class={cn(ADMIN_SELECT, 'h-8 w-32')} value={recipient?.person_id ?? ''} onchange={(e) => (sendTo = e.currentTarget.value)}>
            {#each people as p (p.person_id)}<option value={p.person_id}>{p.name}</option>{/each}
          </select>
        </label>
      {/if}
    </div>

    {#if error}<InlineDestructiveAlert message={error} />{/if}

    {#each takes as t (t.clip.id)}
      <div class="grid gap-2 rounded-md border bg-background p-3">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="font-medium">{t.profile}</span>
          <Badge variant="outline">{t.provider}</Badge>
          <span class="text-xs text-muted-foreground">
            {t.clip.seconds.toFixed(1)} s · {Math.max(1, Math.round(t.clip.bytes / 1024))} KB · made in {t.clip.took_s.toFixed(1)} s ·
            <span title={t.clip.cost_exact ? 'From the usage Gemini reported' : 'Estimated: OpenAI reports no usage'}>{money(t.clip.cost_usd, t.clip.cost_exact)}</span>
          </span>
          <span class="ml-auto flex items-center gap-1">
            {#if recipient}
              <Button size="sm" variant="outline" disabled={t.sending} onclick={() => send(t)}><Send size={13} /> Send to {recipient.name}</Button>
            {/if}
            <a class="inline-flex size-8 items-center justify-center rounded-md hover:bg-accent" href={voiceClipUrl(t.clip.id, true)} title="Download .ogg"
              ><Download size={13} /></a
            >
          </span>
        </div>
        <p class="truncate text-xs text-muted-foreground" title={t.text}>"{t.text}"</p>
        <audio controls class="h-9 w-full" src={voiceClipUrl(t.clip.id)}></audio>
        {#if t.note}<p class="text-xs text-muted-foreground">{t.note}</p>{/if}
      </div>
    {:else}
      <p class="text-sm text-muted-foreground">Takes appear here, newest first, so you can compare voices. Each is a WhatsApp voice note (OGG/Opus).</p>
    {/each}
    {#if takes.length > 1}
      <p class="text-right text-xs text-muted-foreground">This visit: {takes.length} takes, {money(spent, takes.every((t) => t.clip.cost_exact))}</p>
    {/if}
  </div>
</SectionCardMuted>
