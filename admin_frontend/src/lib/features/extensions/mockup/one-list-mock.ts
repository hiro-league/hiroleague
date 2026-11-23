// mockup: the admin's one list of extensions (Unified communication, phase 2), with mock rows.
// Each row has the fields the extensions list (`extension_records`) and an extension's description hold
// today: its name, kind, version, description, offers, uses; the three attributes of its kind (who starts
// it, whether it relays chat, where its settings live); and its live connection. Nothing here is real:
// the labels ("Phones") and the channels' descriptions are written for the mockup, and Echo has no row
// in today's data.

export type ExtensionKind = 'channel' | 'app';

/** A channel's link to its account (WhatsApp's QR code); absent for a channel with no account. */
export type MockLink = { linked: boolean; account: string };

/** One setting of a started extension, drawn from its settings form (`config_schema`). */
export type MockSetting = { key: string; label: string; value: string; secret?: boolean };

/** One thing an app offers, as its description's `offers` holds it today (`knows`, `can_do`). */
export type MockOffer = { name: string; says: string };

export type MockExtension = {
  extension_id: string;
  name: string;
  /** The name people read: the app's site title, or the channel's label. */
  label: string;
  kind: ExtensionKind;
  version: string;
  description: string;
  paired_at: string;
  connected: boolean;
  /** When it connected, or when it was last seen. */
  since: string;
  // The kind's three attributes.
  started_by_core: boolean;
  relays_chat: boolean;
  /** A started extension's switch; an app has none. */
  enabled: boolean | null;
  /** The one channel the core can't run without (phones' chat). */
  mandatory?: boolean;
  link?: MockLink;
  settings?: MockSetting[];
  site?: string;
  offers?: MockOffer[];
  uses?: string[];
};

const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();
const daysAgo = (d: number) => minutesAgo(d * 24 * 60);

export const MOCK_EXTENSIONS: MockExtension[] = [
  {
    extension_id: '2dd5f3dad32f741763afcd968a5d045a',
    name: 'whatsapp',
    label: 'WhatsApp',
    kind: 'channel',
    version: '0.1.0',
    description: "Relays the family's WhatsApp chats to Hiro, and Hiro's replies back.",
    paired_at: minutesAgo(190),
    connected: true,
    since: minutesAgo(190),
    started_by_core: true,
    relays_chat: true,
    enabled: true,
    link: { linked: true, account: "The family's WhatsApp" },
    // The titles of WhatsApp's real settings form (its config_schema); the values are made up.
    settings: [
      { key: 'owner_number', label: 'Owner number', value: 'set', secret: true },
      { key: 'allowed_senders', label: 'Allowed senders', value: '4 people' },
      { key: 'send_read_receipts', label: 'Send read receipts', value: 'On' },
      { key: 'audio_in', label: 'Accept voice notes', value: 'On' },
      { key: 'audio_out', label: 'Reply with voice notes', value: 'On' },
      { key: 'default_character_id', label: 'Default character', value: 'Hiro' }
    ]
  },
  {
    extension_id: '075d9fc1c22b479c3be3814666b6c16a',
    name: 'devices',
    label: 'Phones',
    kind: 'channel',
    version: '0.1.0',
    description: "Relays the family's phones' chat, through the gateway.",
    paired_at: minutesAgo(193),
    connected: true,
    since: minutesAgo(193),
    started_by_core: true,
    relays_chat: true,
    enabled: true,
    mandatory: true,
    settings: []
  },
  {
    extension_id: '9b1e2c7d4f6a4e0c8d3b5a7f1e2d4c6b',
    name: 'echo',
    label: 'Echo',
    kind: 'channel',
    version: '0.1.0',
    description: 'Answers every message with the same words: a channel for tests.',
    paired_at: daysAgo(2),
    connected: false,
    since: daysAgo(2),
    started_by_core: true,
    relays_chat: true,
    enabled: false,
    settings: []
  },
  {
    extension_id: '46a19590fe4c47159acc338c9249dc3c',
    name: 'home',
    label: 'HomeHiro',
    kind: 'app',
    version: '0.1.0',
    description: "HomeHiro: the home's cameras, people and devices",
    paired_at: daysAgo(15),
    connected: true,
    since: minutesAgo(185),
    started_by_core: false,
    relays_chat: false,
    enabled: null,
    site: 'http://home.hiro.local',
    offers: [
      { name: "Home's checks", says: "Whether HomeHiro's MQTT link and the Wake word listener work" },
      { name: 'Devices', says: "The home's devices and what each is doing now" }
    ],
    uses: ['Describe a camera picture', 'Wake word']
  },
  {
    extension_id: 'd9dceac3f89649138bb02926ed8d2e7d',
    name: 'net',
    label: 'NetHiro',
    kind: 'app',
    version: '0.1.0',
    description: "NetHiro: the house's network, internet and machines",
    paired_at: daysAgo(7),
    connected: true,
    since: minutesAgo(184),
    started_by_core: false,
    relays_chat: false,
    enabled: null,
    site: 'http://net.hiro.local',
    offers: [{ name: 'Internet use of some devices', says: 'Bandwidth and usage over a range, for the devices given' }],
    uses: ['Explain an alert']
  },
  {
    extension_id: '572ef1ab35864ab185876c2b01d280a2',
    name: 'reports',
    label: 'CodeHiro',
    kind: 'app',
    version: '0.1.0',
    description: "CodeHiro: each project's code, day by day",
    paired_at: daysAgo(11),
    connected: true,
    since: minutesAgo(184),
    started_by_core: false,
    relays_chat: false,
    enabled: null,
    site: 'http://reports.local',
    offers: [],
    uses: ['Review']
  },
  {
    extension_id: '4a2b76c5c159471ab5ba4981ab8310a3',
    name: 'train',
    label: 'Fine tuning',
    kind: 'app',
    version: '0.1.0',
    description: "TrainHiro: AI fine tuning of Frigate's face and body recognition",
    paired_at: daysAgo(7),
    connected: false,
    since: daysAgo(1),
    started_by_core: false,
    relays_chat: false,
    enabled: null,
    site: 'http://train.hiro.local',
    offers: [],
    uses: []
  },
  {
    extension_id: '282ce3518c02493190a7dea513de7116',
    name: 'study',
    label: 'Study',
    kind: 'app',
    version: '0.1.0',
    description: "StudyHiro: the kids' study tracker, with an AI agent that makes exercises and reviews answers",
    paired_at: daysAgo(7),
    connected: true,
    since: minutesAgo(183),
    started_by_core: false,
    relays_chat: false,
    enabled: null,
    site: 'http://study.hiro.local',
    offers: [],
    uses: ['Make exercises', 'Review answers']
  },
  {
    extension_id: 'ca95e15c85de4f78a7aa4ba81c7dcc66',
    name: 'eval',
    label: 'EvalHiro',
    kind: 'app',
    version: '0.1.0',
    description: "EvalHiro: evaluates Hiro's memory on eval corpora",
    paired_at: daysAgo(6),
    connected: false,
    since: daysAgo(6),
    started_by_core: false,
    relays_chat: false,
    enabled: null,
    site: 'http://eval.hiro.local',
    offers: [],
    uses: ['Answer', 'Judge']
  }
];

/** Channels first (the family's chat), then apps; each by its label. */
export function sortExtensions(rows: MockExtension[]): MockExtension[] {
  return [...rows].sort(
    (a, b) => (a.kind === b.kind ? a.label.localeCompare(b.label) : a.kind === 'channel' ? -1 : 1)
  );
}

export type StatusLine = { tone: 'ok' | 'off' | 'warn'; text: string };

/** What the Status column says: off, connected, or not connected; a channel's link when it has one. */
export function statusOf(row: MockExtension): StatusLine {
  if (row.enabled === false) return { tone: 'off', text: 'Off' };
  if (!row.connected) return { tone: 'warn', text: 'Not connected' };
  if (row.link && !row.link.linked) return { tone: 'warn', text: 'Connected, not linked' };
  return { tone: 'ok', text: 'Connected' };
}
