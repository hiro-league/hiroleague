/**
 * State for the Phase 7a AI pages: AI profiles and Uses, and the Providers tab's local-server and
 * plan-tool rows with their dialogs. Everything comes from the API (`$lib/api/ai`, preferences).
 *
 * - Profiles: listed by `GET /api/ai/profiles` (with today's use and readiness); created, changed
 *   and deleted through the preferences PATCH (`ai.profiles.<id>`), the way Image Lab edits
 *   `image_profiles`. The server validates the fallback chain too; the editor checks it first.
 * - Hiro's jobs (Phase 7b step 5): the same list returns `jobs` (each job's field → one profile);
 *   a job's pick is a preferences PATCH of its field. A job's default profile (`preset`) can't be
 *   deleted; Restore default (`POST /api/ai/profiles/<id>/restore-default`) resets its tuning.
 * - Try it: `POST /api/ai/try` with the editor's draft (saved or not).
 * - Uses: `GET /api/ai/uses` per extension (new / removed marked by the server), set / forget /
 *   refresh through their routes.
 * - Plan tools (Claude Code, Codex): `/api/ai/plans` status, sign-in (start → link / code → poll
 *   state), sign-out, test question, npm update (polled while it runs).
 * - Local servers (LM Studio, Ollama): `/api/ai/local-servers` (checked now), check, settings.
 * - The model picker is the shared `SingleModelPicker`, fed catalog chat models, the models local
 *   servers reported and the models each plan tool lists.
 */
import {
  checkLocalServer,
  forgetAiUse,
  getPlans,
  listAiLocalModels,
  listAiProfiles,
  listAiUses,
  listLocalServers,
  planSignIn,
  planSignOut,
  planTest,
  refreshAiUses,
  restoreAiProfileDefault,
  setAiUse,
  setLocalServer,
  tryAiProfile,
  updatePlans,
  type AiLocalModel,
  type LocalServerStatus,
  type PlanSignIn,
  type PlanTestPayload,
  type PlanToolStatus,
  type PlanUpdates
} from '$lib/api/ai';
import { listCatalogModels, type CatalogModelRow, type CatalogProviderRow } from '$lib/api/catalog';
import type { AiProfile as AiProfilePrefs } from '$lib/api/generated/preferences.generated';
import { patchPreferences } from '$lib/api/preferences';
import type { Notify } from '$kit/ui/toast.svelte';
import {
  jobFromRow,
  localModelCatalogRows,
  planModelCatalogRows,
  profileFromRow,
  profileToPrefs,
  tryResultFrom,
  usesFromPayload
} from './ai-api-mapping';
import {
  aiProvidersFromCatalog,
  checkDraftFallback,
  findModel,
  LOCAL_SERVER_KIND_LABELS,
  PLAN_HOSTING,
  profileIdFor,
  TEMPERATURE_IGNORED,
  temperatureNote,
  thinkingFor
} from './ai-profile-rules';
import type { AiCatalogModelRow, AiJob, AiProfile, AiProviderKind, AiTryResult, AiUse, AiUsesGroup } from './ai-types';

export type AiController = ReturnType<typeof createAiController>;

/** What the AI pages read from the page's catalog controller (providers + configured state). */
export type AiCatalogSource = {
  readonly providers: CatalogProviderRow[];
  readonly configuredWorkspaceProviderIds: Set<string>;
  readonly activeProvidersStore: { readonly resolved: boolean };
};

/** How often a waiting sign-in and a running update are polled. */
const SIGN_IN_POLL_MS = 3000;
const UPDATE_POLL_MS = 5000;

export type LocalServerDraft = { baseUrl: string; unloadIdleMin: number; context: number; batch: number };

function copy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

function blankProfile(id: string): AiProfile {
  return {
    id,
    name: '',
    model: '',
    thinking: null,
    temperature: null,
    maxTokens: null,
    context: null,
    instructions: '',
    budget: { costPerDay: 1, perHour: null, atOnce: 1 },
    fallbackId: null,
    usage: { todayAsks: 0, todayCost: 0, thisHour: 0 },
    preset: null,
    jobs: []
  };
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the picture.'));
    reader.readAsDataURL(file);
  });
}

export function createAiController(notify: Notify, catalog: AiCatalogSource) {
  // ── profiles ──────────────────────────────────────────────────────────
  let profiles = $state<AiProfile[]>([]);
  /** `ai.uses` as stored (key → profile id), from the profiles list. */
  let rawUses = $state<Record<string, string | null>>({});
  let profilesLoading = $state(true);
  let profilesError = $state<string | null>(null);
  /** Phase 7b step 5: Hiro's own jobs, each pointing at one profile (from the profiles list). */
  let jobs = $state<AiJob[]>([]);
  let jobBusy = $state<Record<string, boolean>>({});

  // ── uses ──────────────────────────────────────────────────────────────
  let uses = $state<AiUse[]>([]);
  let useGroups = $state<AiUsesGroup[]>([]);
  let usesLoading = $state(true);
  let usesError = $state<string | null>(null);
  let refreshingExtensions = $state<Record<string, boolean>>({});
  let useBusy = $state<Record<string, boolean>>({});

  // ── plan tools ────────────────────────────────────────────────────────
  let plans = $state<PlanToolStatus[]>([]);
  let planUpdates = $state<PlanUpdates | null>(null);
  let plansError = $state<string | null>(null);
  let planBusy = $state<Record<string, string>>({});
  let planTests = $state<Record<string, PlanTestPayload | null>>({});
  /** The sign-in shown in a tool's dialog (start / poll / code), by tool id. */
  let signIns = $state<Record<string, PlanSignIn | null>>({});
  let signInCodes = $state<Record<string, string>>({});
  const signInTimers = new Map<string, number>();
  let updateTimer = 0;

  // ── local servers ─────────────────────────────────────────────────────
  let servers = $state<LocalServerStatus[]>([]);
  let serversLoading = $state(true);
  let serversError = $state<string | null>(null);
  let checkingServerIds = $state<Record<string, boolean>>({});
  let serverDraft = $state<LocalServerDraft>({ baseUrl: '', unloadIdleMin: 60, context: 16384, batch: 2048 });
  let serverSaving = $state(false);

  /** Provider whose dialog is open (a local server or a plan tool), or null. */
  let dialogProviderId = $state<string | null>(null);

  // ── catalog plumbing for the shared SingleModelPicker ─────────────────
  let catalogChatModels = $state<AiCatalogModelRow[]>([]);
  let localModels = $state<AiLocalModel[]>([]);
  let catalogLoaded = $state(false);

  const pickerModels = $derived.by<AiCatalogModelRow[]>(() => {
    const local = localModelCatalogRows(localModels);
    const localIds = new Set(local.map((m) => m.id));
    return [
      ...catalogChatModels.filter((m) => !localIds.has(m.id)),
      ...local,
      ...plans.flatMap(planModelCatalogRows)
    ];
  });

  /** Catalog providers, plus a plan tool the catalog doesn't list (defensive: it lists both today). */
  const pickerProviders = $derived<CatalogProviderRow[]>([
    ...catalog.providers,
    ...plans
      .filter((t) => !catalog.providers.some((p) => p.id === t.id))
      .map((t): CatalogProviderRow => ({ id: t.id, display_name: t.name, hosting: PLAN_HOSTING }))
  ]);

  /** Configured in the workspace, local servers with an address, and signed-in plan tools. */
  const pickerActiveIds = $derived(
    new Set([
      ...catalog.configuredWorkspaceProviderIds,
      ...servers.filter((s) => s.configured || s.base_url).map((s) => s.provider_id),
      ...plans.filter((t) => t.signed_in).map((t) => t.id)
    ])
  );

  function kindOf(providerId: string, hosting: string | null | undefined): AiProviderKind {
    if (hosting === PLAN_HOSTING || plans.some((t) => t.id === providerId)) return 'plan';
    return hosting === 'local' ? 'local' : 'api';
  }

  function notReadyOf(providerId: string): string | null {
    const tool = plans.find((t) => t.id === providerId);
    if (tool && !tool.installed) return `${tool.name} isn't installed (Update now installs it).`;
    if (tool && !tool.signed_in) return `${tool.name} is signed out.`;
    const server = servers.find((s) => s.provider_id === providerId);
    const label = LOCAL_SERVER_KIND_LABELS[providerId] ?? providerId;
    if (server?.state === 'down') return `${label} is down: ${server.error ?? "can't connect"}.`;
    if (server?.state === 'no_address') return `${label} has no address set.`;
    return null;
  }

  const providers = $derived(
    aiProvidersFromCatalog({
      models: pickerModels,
      providers: pickerProviders,
      kindOf,
      notReadyOf,
      temperatureIgnored: TEMPERATURE_IGNORED
    })
  );

  // ── loading ───────────────────────────────────────────────────────────

  async function loadCatalog() {
    try {
      const [chat, local] = await Promise.all([listCatalogModels({ model_kind: 'chat' }), listAiLocalModels()]);
      catalogChatModels = chat.models;
      // The servers' live check (loadServers) may already have filled this with fresher rows.
      if (!localModels.length) localModels = local.models;
    } catch (err) {
      notify('error', errorText(err, 'Could not load the models for the picker.'));
    } finally {
      catalogLoaded = true;
    }
  }

  async function loadProfiles() {
    try {
      const payload = await listAiProfiles();
      profiles = payload.profiles.map(profileFromRow);
      rawUses = payload.uses ?? {};
      jobs = (payload.jobs ?? []).map(jobFromRow);
      profilesError = null;
    } catch (err) {
      profilesError = errorText(err, 'Could not load the AI profiles.');
    } finally {
      profilesLoading = false;
    }
  }

  async function loadUses() {
    try {
      const payload = await listAiUses();
      const mapped = usesFromPayload(payload.extensions);
      uses = mapped.uses;
      useGroups = mapped.groups;
      usesError = null;
    } catch (err) {
      usesError = errorText(err, 'Could not load the uses.');
    } finally {
      usesLoading = false;
    }
  }

  async function loadPlans(fresh = false) {
    try {
      const payload = await getPlans(fresh);
      plans = payload.tools;
      planUpdates = payload.updates;
      plansError = null;
      if (planUpdates.running) scheduleUpdatePoll();
    } catch (err) {
      plansError = errorText(err, 'Could not read Claude Code and Codex.');
    }
  }

  async function loadServers() {
    try {
      const payload = await listLocalServers();
      servers = payload.servers;
      localModels = servers.flatMap((s) => s.models);
      serversError = null;
    } catch (err) {
      serversError = errorText(err, 'Could not check the local servers.');
    } finally {
      serversLoading = false;
    }
  }

  async function initialize() {
    await Promise.all([loadCatalog(), loadProfiles(), loadUses(), loadPlans(), loadServers()]);
  }

  /** Stop the pollers (page unmount). A sign-in or update keeps going on the server. */
  function dispose() {
    for (const handle of signInTimers.values()) window.clearTimeout(handle);
    signInTimers.clear();
    if (updateTimer) window.clearTimeout(updateTimer);
    updateTimer = 0;
  }

  // ── profile editor ────────────────────────────────────────────────────
  let editorOpen = $state(false);
  let editorIsNew = $state(false);
  let saving = $state(false);
  let draft = $state<AiProfile>(blankProfile(''));
  const draftModel = $derived(findModel(providers, draft.model));
  const draftCheck = $derived(checkDraftFallback(profiles, draft));
  const draftTemperatureNote = $derived(temperatureNote(draftModel.provider, draft.thinking));

  let deletingId = $state<string | null>(null);
  let deleting = $state(false);
  let restoringId = $state<string | null>(null);
  let restoring = $state(false);

  // ── try it (inside the editor) ────────────────────────────────────────
  let tryPrompt = $state('Is anyone at the front door?');
  let tryPicture = $state<{ name: string; url: string; dataUrl: string } | null>(null);
  let trying = $state(false);
  let tryResult = $state<AiTryResult | null>(null);
  let tryError = $state<string | null>(null);

  function profileName(id: string | null): string {
    return (id && profiles.find((p) => p.id === id)?.name) || '';
  }

  function modelOf(profile: AiProfile) {
    return findModel(providers, profile.model);
  }

  /** Hiro's jobs whose own field points at this profile, by name ("Hiro's chat, Eval: judge"). */
  function jobsUsing(id: string): string[] {
    return jobs.filter((j) => j.profileId === id).map((j) => j.label);
  }

  function jobLabel(id: string | null): string {
    return (id && jobs.find((j) => j.id === id)?.label) || '';
  }

  /** What would break if this profile went away: uses pointing at it, profiles falling back to it
   *  (Hiro's jobs are listed apart, by `jobsUsing`). */
  function usedBy(id: string): string[] {
    const useLabels = Object.entries(rawUses)
      .filter(([, pid]) => pid === id)
      .map(([key]) => uses.find((u) => u.id === key)?.label ?? key);
    return [...useLabels, ...profiles.filter((p) => p.fallbackId === id).map((p) => `${p.name} (fallback)`)];
  }

  function openEditor(next: AiProfile, isNew: boolean) {
    draft = next;
    editorIsNew = isNew;
    tryResult = null;
    tryError = null;
    editorOpen = true;
  }

  function takenIds(): Set<string> {
    return new Set(profiles.map((p) => p.id));
  }

  function newProfile() {
    openEditor(blankProfile(profileIdFor('new profile', takenIds())), true);
  }

  function editProfile(id: string) {
    const found = profiles.find((p) => p.id === id);
    if (found) openEditor(copy(found), false);
  }

  function duplicateProfile(id: string) {
    const found = profiles.find((p) => p.id === id);
    if (!found) return;
    const name = `${found.name} (copy)`;
    openEditor(
      {
        ...copy(found),
        id: profileIdFor(name, takenIds()),
        name,
        usage: { todayAsks: 0, todayCost: 0, thisHour: 0 },
        // Phase 7b step 5: a copy of a job's default is an ordinary profile (deletable, no Restore).
        preset: null,
        jobs: []
      },
      true
    );
  }

  function closeEditor() {
    editorOpen = false;
    void setTryPicture(null);
  }

  /** Switch the draft's model (null = cleared), keeping the other fields valid for its provider kind. */
  function setDraftModel(ref: string | null) {
    const { provider, model } = findModel(providers, ref ?? '');
    const kind = provider?.kind ?? 'api';
    draft.model = ref ?? '';
    draft.thinking = thinkingFor(model, draft.thinking);
    if (temperatureNote(provider, draft.thinking)) draft.temperature = null;
    draft.context = kind === 'local' ? (draft.context ?? 8192) : null;
    if (kind === 'api') {
      draft.budget.costPerDay = draft.budget.costPerDay ?? 1;
      draft.budget.perHour = null;
    } else {
      draft.budget.perHour = draft.budget.perHour ?? 30;
      draft.budget.costPerDay = null;
    }
  }

  async function saveProfile() {
    const name = draft.name.trim();
    if (!name) {
      notify('error', 'Give the profile a name.');
      return;
    }
    if (!draft.model) {
      notify('error', 'Pick a model.');
      return;
    }
    if (draftCheck.message) {
      notify('error', draftCheck.message);
      return;
    }
    // A new profile's id comes from its name (the backend wants a lowercase slug).
    const id = editorIsNew ? profileIdFor(name, takenIds()) : draft.id;
    saving = true;
    try {
      await patchPreferences({ [`ai.profiles.${id}`]: profileToPrefs({ ...draft, name }) });
      notify('success', `Saved ${name}.`);
      closeEditor();
      await loadProfiles();
    } catch (err) {
      notify('error', errorText(err, 'Could not save the profile.'));
    } finally {
      saving = false;
    }
  }

  function askDelete(id: string) {
    deletingId = id;
  }

  /** Delete in one atomic PATCH: the profile, fallbacks pointing at it, uses that asked it, and Hiro's
   *  jobs that pointed at it (they borrow their fallback job's profile; the server refuses a job field
   *  naming a missing profile). A job's default profile has no Delete. */
  async function confirmDelete() {
    const id = deletingId;
    if (!id) return;
    const name = profileName(id);
    const rest: Record<string, AiProfilePrefs> = {};
    for (const p of profiles) {
      if (p.id === id) continue;
      rest[p.id] = profileToPrefs(p.fallbackId === id ? { ...p, fallbackId: null } : p);
    }
    const nextUses = Object.fromEntries(Object.entries(rawUses).map(([key, pid]) => [key, pid === id ? null : pid]));
    const jobEdits = Object.fromEntries(jobs.filter((j) => j.profileId === id).map((j) => [j.path, null]));
    deleting = true;
    try {
      await patchPreferences({ 'ai.profiles': rest, 'ai.uses': nextUses, ...jobEdits });
      notify('success', `Deleted ${name}.`);
      deletingId = null;
      await Promise.all([loadProfiles(), loadUses()]);
    } catch (err) {
      notify('error', errorText(err, 'Could not delete the profile.'));
    } finally {
      deleting = false;
    }
  }

  // ── Hiro's jobs (Phase 7b step 5) ─────────────────────────────────────

  function askRestore(id: string) {
    restoringId = id;
  }

  /** Restore default: the job's preset tuning back on its default profile (model, limits, fallback kept). */
  async function confirmRestore() {
    const id = restoringId;
    if (!id) return;
    const name = profileName(id);
    restoring = true;
    try {
      await restoreAiProfileDefault(id);
      notify('success', `${name} is back to its default settings.`);
      restoringId = null;
      await loadProfiles();
    } catch (err) {
      notify('error', errorText(err, 'Could not restore the profile.'));
    } finally {
      restoring = false;
    }
  }

  /** Point one of Hiro's jobs at a profile ('' = not set: it borrows its fallback job's profile). */
  async function setJobProfile(jobId: string, profileId: string) {
    const job = jobs.find((j) => j.id === jobId);
    if (!job) return;
    jobBusy = { ...jobBusy, [jobId]: true };
    try {
      await patchPreferences({ [job.path]: profileId || null });
      const parent = jobLabel(job.fallsBackTo);
      notify(
        'success',
        profileId
          ? `${job.label} now asks ${profileName(profileId) || profileId}.`
          : parent
            ? `${job.label} now borrows ${parent}'s profile.`
            : `${job.label} is off.`
      );
      await loadProfiles();
    } catch (err) {
      notify('error', errorText(err, 'Could not change the profile.'));
    } finally {
      jobBusy = { ...jobBusy, [jobId]: false };
    }
  }

  // ── uses ──────────────────────────────────────────────────────────────

  async function setUseProfile(useKey: string, profileId: string) {
    const use = uses.find((u) => u.id === useKey);
    useBusy = { ...useBusy, [useKey]: true };
    try {
      await setAiUse(useKey, profileId || null);
      notify('success', `${use?.label ?? 'Use'} now asks ${profileName(profileId) || 'no profile'}.`);
      await Promise.all([loadUses(), loadProfiles()]);
    } catch (err) {
      notify('error', errorText(err, 'Could not change the profile.'));
    } finally {
      useBusy = { ...useBusy, [useKey]: false };
    }
  }

  /** Ask the extension for its uses again (it can change them without telling the core). */
  async function refreshUses(group: AiUsesGroup) {
    if (!group.extensionId) return;
    refreshingExtensions = { ...refreshingExtensions, [group.extension]: true };
    try {
      const payload = await refreshAiUses(group.extensionId);
      const failed = payload.failed[0];
      if (failed) notify('warning', `${failed.extension}: ${failed.error}`);
      else if (payload.note) notify('info', payload.note);
      else notify('success', `${group.extension}: uses refreshed.`);
      await loadUses();
    } catch (err) {
      notify('error', errorText(err, `Could not ask ${group.extension} for its uses.`));
    } finally {
      refreshingExtensions = { ...refreshingExtensions, [group.extension]: false };
    }
  }

  /** Drop a use the extension no longer offers (its profile choice goes with it). */
  async function forgetUse(useKey: string) {
    const use = uses.find((u) => u.id === useKey);
    useBusy = { ...useBusy, [useKey]: true };
    try {
      await forgetAiUse(useKey);
      notify('success', `Forgot ${use?.label ?? 'the use'}.`);
      await Promise.all([loadUses(), loadProfiles()]);
    } catch (err) {
      notify('error', errorText(err, 'Could not forget the use.'));
    } finally {
      useBusy = { ...useBusy, [useKey]: false };
    }
  }

  // ── try it ────────────────────────────────────────────────────────────

  async function setTryPicture(file: File | null) {
    if (tryPicture) URL.revokeObjectURL(tryPicture.url);
    tryPicture = null;
    tryResult = null;
    if (!file) return;
    try {
      tryPicture = { name: file.name, url: URL.createObjectURL(file), dataUrl: await readAsDataUrl(file) };
    } catch (err) {
      notify('error', errorText(err, 'Could not read the picture.'));
    }
  }

  async function tryIt() {
    if (!tryPrompt.trim() || !draft.model) return;
    trying = true;
    tryResult = null;
    tryError = null;
    const kind = draftModel.provider?.kind;
    try {
      // The draft as it is in the editor, saved or not (a name is required by the profile shape).
      const payload = await tryAiProfile({
        prompt: tryPrompt,
        draft: { ...profileToPrefs(draft), label: draft.name.trim() || 'Try it' },
        picture: tryPicture?.dataUrl ?? null
      });
      const mapped = tryResultFrom(payload, kind);
      tryResult = mapped.result;
      tryError = mapped.error;
    } catch (err) {
      tryError = errorText(err, 'The ask failed.');
    } finally {
      trying = false;
    }
  }

  // ── provider dialogs ──────────────────────────────────────────────────

  function openProviderDialog(id: string) {
    dialogProviderId = id;
    const server = servers.find((s) => s.provider_id === id);
    if (server) {
      serverDraft = {
        baseUrl: server.base_url ?? '',
        unloadIdleMin: server.unload_idle_min,
        context: server.context,
        batch: server.batch
      };
    }
    // A sign-in already running on the server: show it and keep polling.
    const tool = plans.find((t) => t.id === id);
    if (tool && tool.sign_in.state === 'waiting') {
      signIns = { ...signIns, [id]: tool.sign_in };
      scheduleSignInPoll(id);
    }
  }

  function closeProviderDialog() {
    const id = dialogProviderId;
    dialogProviderId = null;
    if (id) stopSignInPoll(id);
  }

  // ── local servers ─────────────────────────────────────────────────────

  function serverFor(providerId: string): LocalServerStatus | undefined {
    return servers.find((s) => s.provider_id === providerId);
  }

  function replaceServer(next: LocalServerStatus) {
    servers = servers.some((s) => s.provider_id === next.provider_id)
      ? servers.map((s) => (s.provider_id === next.provider_id ? next : s))
      : [...servers, next];
    localModels = servers.flatMap((s) => s.models);
  }

  async function checkServer(id: string) {
    checkingServerIds = { ...checkingServerIds, [id]: true };
    try {
      const payload = await checkLocalServer(id);
      replaceServer(payload);
      const label = LOCAL_SERVER_KIND_LABELS[id] ?? id;
      if (payload.state === 'up') notify('success', `${label} is up: ${payload.models.length} models.`);
      else notify('warning', `${label}: ${payload.error ?? payload.state}.`);
    } catch (err) {
      notify('error', errorText(err, 'Could not check the server.'));
    } finally {
      checkingServerIds = { ...checkingServerIds, [id]: false };
    }
  }

  /** Save the dialog's address and load settings (context / batch for LM Studio only), then check. */
  async function saveServer(id: string) {
    serverSaving = true;
    try {
      await setLocalServer(id, {
        base_url: serverDraft.baseUrl.trim() || null,
        unload_idle_min: serverDraft.unloadIdleMin || null,
        context: id === 'lm_studio' ? serverDraft.context || null : null,
        batch: id === 'lm_studio' ? serverDraft.batch || null : null
      });
      notify('success', `Saved ${LOCAL_SERVER_KIND_LABELS[id] ?? id}.`);
      await checkServer(id);
    } catch (err) {
      notify('error', errorText(err, 'Could not save the server.'));
    } finally {
      serverSaving = false;
    }
  }

  function profilesOnProvider(id: string): string[] {
    return profiles.filter((p) => p.model.startsWith(`${id}:`)).map((p) => p.name);
  }

  // ── plan tools ────────────────────────────────────────────────────────

  function setPlanBusy(id: string, label: string) {
    planBusy = { ...planBusy, [id]: label };
  }

  function stopSignInPoll(id: string) {
    const handle = signInTimers.get(id);
    if (handle) window.clearTimeout(handle);
    signInTimers.delete(id);
  }

  function scheduleSignInPoll(id: string) {
    stopSignInPoll(id);
    signInTimers.set(id, window.setTimeout(() => void pollSignIn(id), SIGN_IN_POLL_MS));
  }

  /** Apply a sign-in answer: keep polling while it waits; on done, re-read who is signed in. */
  async function applySignIn(id: string, next: PlanSignIn) {
    signIns = { ...signIns, [id]: next };
    if (next.state === 'waiting') {
      if (dialogProviderId === id) scheduleSignInPoll(id);
      return;
    }
    stopSignInPoll(id);
    if (next.state === 'done') {
      const name = plans.find((t) => t.id === id)?.name ?? id;
      notify('success', `${name} is signed in.`);
      signIns = { ...signIns, [id]: null };
      await loadPlans(true);
    }
  }

  async function pollSignIn(id: string) {
    signInTimers.delete(id);
    try {
      const payload = await planSignIn(id, 'state');
      await applySignIn(id, payload);
    } catch (err) {
      notify('error', errorText(err, 'Could not read the sign-in.'));
    }
  }

  async function signIn(id: string) {
    setPlanBusy(id, 'Starting the sign-in…');
    try {
      const payload = await planSignIn(id, 'start');
      signInCodes = { ...signInCodes, [id]: '' };
      await applySignIn(id, payload);
    } catch (err) {
      notify('error', errorText(err, 'Could not start the sign-in.'));
    } finally {
      setPlanBusy(id, '');
    }
  }

  /** Claude Code: paste back the code its page shows. */
  async function sendSignInCode(id: string) {
    const code = (signInCodes[id] ?? '').trim();
    if (!code) return;
    setPlanBusy(id, 'Sending the code…');
    try {
      const payload = await planSignIn(id, 'code', code);
      await applySignIn(id, payload);
    } catch (err) {
      notify('error', errorText(err, 'Could not send the code.'));
    } finally {
      setPlanBusy(id, '');
    }
  }

  async function cancelSignIn(id: string) {
    stopSignInPoll(id);
    try {
      await planSignIn(id, 'cancel');
    } catch (err) {
      notify('error', errorText(err, 'Could not cancel the sign-in.'));
    }
    signIns = { ...signIns, [id]: null };
    await loadPlans();
  }

  async function signOut(id: string) {
    setPlanBusy(id, 'Signing out…');
    try {
      const payload = await planSignOut(id);
      if (payload.signed_out) notify('success', 'Signed out.');
      else notify('warning', payload.message ?? 'The tool did not confirm the sign-out.');
      planTests = { ...planTests, [id]: null };
      await loadPlans(true);
    } catch (err) {
      notify('error', errorText(err, 'Could not sign out.'));
    } finally {
      setPlanBusy(id, '');
    }
  }

  async function testQuestion(id: string) {
    setPlanBusy(id, 'Asking a test question…');
    planTests = { ...planTests, [id]: null };
    try {
      const payload = await planTest(id);
      planTests = { ...planTests, [id]: payload };
    } catch (err) {
      notify('error', errorText(err, 'The test question failed.'));
    } finally {
      setPlanBusy(id, '');
    }
  }

  function scheduleUpdatePoll() {
    if (updateTimer) return;
    updateTimer = window.setTimeout(() => void pollUpdate(), UPDATE_POLL_MS);
  }

  async function pollUpdate() {
    updateTimer = 0;
    const wasRunning = planUpdates?.running;
    await loadPlans();
    if (wasRunning && planUpdates && !planUpdates.running) {
      notify(planUpdates.ok === false ? 'error' : 'success', planUpdates.message || 'Update finished.');
    }
  }

  /** npm install / update of both tools, in the background; polled while it runs. */
  async function updateNow() {
    try {
      const payload = await updatePlans();
      planUpdates = payload.updates;
      notify('info', 'Updating Claude Code and Codex…');
      scheduleUpdatePoll();
    } catch (err) {
      notify('error', errorText(err, 'Could not start the update.'));
    }
  }

  return {
    get profiles() {
      return profiles;
    },
    get profilesLoading() {
      return profilesLoading;
    },
    get profilesError() {
      return profilesError;
    },
    get jobs() {
      return jobs;
    },
    get jobBusy() {
      return jobBusy;
    },
    get restoringId() {
      return restoringId;
    },
    get restoring() {
      return restoring;
    },
    get uses() {
      return uses;
    },
    get useGroups() {
      return useGroups;
    },
    get usesLoading() {
      return usesLoading;
    },
    get usesError() {
      return usesError;
    },
    get refreshingExtensions() {
      return refreshingExtensions;
    },
    get useBusy() {
      return useBusy;
    },
    get plans() {
      return plans;
    },
    get planUpdates() {
      return planUpdates;
    },
    get plansError() {
      return plansError;
    },
    get planBusy() {
      return planBusy;
    },
    get planTests() {
      return planTests;
    },
    get signIns() {
      return signIns;
    },
    /** Pasted sign-in codes by tool id — bind the dialog's input to `signInCodes[id]`. */
    get signInCodes() {
      return signInCodes;
    },
    get servers() {
      return servers;
    },
    get serversLoading() {
      return serversLoading;
    },
    get serversError() {
      return serversError;
    },
    get checkingServerIds() {
      return checkingServerIds;
    },
    /** The open server dialog's fields — bind inputs to them. */
    get serverDraft() {
      return serverDraft;
    },
    get serverSaving() {
      return serverSaving;
    },
    get dialogProviderId() {
      return dialogProviderId;
    },
    get providers() {
      return providers;
    },
    /** Catalog-shaped rows for `SingleModelPicker` (catalog chat + local servers' + plan tools'). */
    get pickerModels(): CatalogModelRow[] {
      return pickerModels;
    },
    get pickerProviders() {
      return pickerProviders;
    },
    get pickerActiveIds() {
      return pickerActiveIds;
    },
    get pickerActiveResolved() {
      return catalog.activeProvidersStore.resolved;
    },
    get catalogLoaded() {
      return catalogLoaded;
    },
    get editorOpen() {
      return editorOpen;
    },
    get editorIsNew() {
      return editorIsNew;
    },
    get saving() {
      return saving;
    },
    /** The profile being edited — bind inputs to its fields. */
    get draft() {
      return draft;
    },
    get draftModel() {
      return draftModel;
    },
    get draftCheck() {
      return draftCheck;
    },
    get draftTemperatureNote() {
      return draftTemperatureNote;
    },
    get deletingId() {
      return deletingId;
    },
    get deleting() {
      return deleting;
    },
    get tryPrompt() {
      return tryPrompt;
    },
    set tryPrompt(value: string) {
      tryPrompt = value;
    },
    get tryPicture() {
      return tryPicture;
    },
    get trying() {
      return trying;
    },
    get tryResult() {
      return tryResult;
    },
    get tryError() {
      return tryError;
    },
    initialize,
    dispose,
    reload: () => Promise.all([loadProfiles(), loadUses()]),
    reloadProviders: () => Promise.all([loadPlans(true), loadServers()]),
    profileName,
    modelOf,
    usedBy,
    jobsUsing,
    jobLabel,
    newProfile,
    editProfile,
    duplicateProfile,
    closeEditor,
    setDraftModel,
    saveProfile,
    askDelete,
    cancelDelete: () => (deletingId = null),
    confirmDelete,
    askRestore,
    cancelRestore: () => (restoringId = null),
    confirmRestore,
    setJobProfile,
    setUseProfile,
    refreshUses,
    forgetUse,
    setTryPicture,
    tryIt,
    openProviderDialog,
    closeProviderDialog,
    serverFor,
    checkServer,
    saveServer,
    profilesOnProvider,
    signIn,
    sendSignInCode,
    cancelSignIn,
    signOut,
    testQuestion,
    updateNow
  };
}
