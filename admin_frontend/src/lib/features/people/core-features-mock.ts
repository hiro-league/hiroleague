// mockup: Permissions phase 2. The core's own features as the core will declare them (source `hiroleague`), with
// the map Michel locked as each role's grants. Shown on People → Roles and Compare; edits stay in this page and are
// never sent (the core keeps only what is declared, and declares none of these yet).
import type { AccessFeature, AccessRight, AccessSource } from '$lib/api/people';

export const CORE_SOURCE = 'hiroleague';

const r = (id: string, name: string, says: string, personal = false): AccessRight => ({ id, name, says, personal });
const see = (what: string, personal = false) => r('see', 'See', what, personal);
const change = (what: string, personal = false) => r('change', 'Change', what, personal);
const f = (id: string, name: string, rights: AccessRight[]): AccessFeature => ({ id, name, rights, not_for_owner: false });

/** The areas that group several features, by id: the name the Roles page shows over them. */
export const CORE_AREAS: Record<string, string> = { assistant: 'Hiro', ai: 'AI', logs: 'Logs' };

export const CORE_FEATURES_MOCK: AccessFeature[] = [
  f('assistant', 'Talking to Hiro', [r('talk', 'Talk', 'On a chat channel, a device or the admin\'s chat')]),
  f('assistant.characters', 'Characters', [see("Hiro's characters"), change('Add and change characters')]),
  f('conversations', 'Conversations', [see('Conversations and their messages', true), change('Rename, clear and delete', true)]),
  f('memories', 'Memories', [see('What Hiro remembers', true), change('Correct and forget', true)]),
  f('knowledge', 'Knowledge', [see('The knowledge base'), change('Add, change and remove documents')]),
  f('ai.providers', 'Providers and models', [see('Providers, models and what is on'), change('Keys and models')]),
  f('ai.profiles', 'Profiles', [see('Which model and voice does each job'), change('Change the profiles and their uses')]),
  f('ai.images', 'Pictures', [r('run', 'Make pictures', 'Image Lab, which is paid')]),
  f('extensions', 'Extensions', [see('Apps and chat channels'), change('Pair, start, stop and set them up')]),
  f('devices', 'Devices', [see('Paired devices'), change('Pair and remove devices')]),
  f('logs', 'Logs', [see('The logs and their stories')]),
  f('logs.runs', 'Graph runs', [see('What Hiro recalled about people')]),
  f('logs.usage', 'AI usage', [see('Its cost, per person')]),
  f('server', 'Server', [see('Workspaces, gateways, metrics'), change('Restart and set up the server')]),
  f('settings', 'Settings', [see('How Hiro behaves'), change('Change it')])
];

export const coreSourceMock = (): AccessSource => ({
  id: CORE_SOURCE,
  name: 'HiroLeague',
  kind: 'core',
  extension_id: '',
  connected: true,
  features: CORE_FEATURES_MOCK
});

/** Each role's keys in the core, as the locked map grants them (Owner holds everything). */
export const CORE_GRANTS_MOCK: Record<string, string[]> = {
  adult: ['assistant.talk', 'conversations.see:own', 'conversations.change:own', 'memories.see:own', 'memories.change:own'],
  kid: ['assistant.talk', 'conversations.see:own', 'conversations.change:own', 'memories.see:own']
};

/**
 * Features in their areas, in order: a feature with no area is a group of its own (area null); the features of an
 * area (its own id, then `area.<feature>`) are one group under the area's name.
 */
export function groupByArea(
  features: readonly AccessFeature[],
  areas: Readonly<Record<string, string>>
): { area: string | null; name: string; features: AccessFeature[] }[] {
  const out: { area: string | null; name: string; features: AccessFeature[] }[] = [];
  for (const feature of features) {
    const head = feature.id.split('.')[0];
    const area = head in areas ? head : null;
    const last = out.at(-1);
    if (area !== null && last?.area === area) last.features.push(feature);
    else out.push({ area, name: area !== null ? areas[area] : feature.name, features: [feature] });
  }
  return out;
}
