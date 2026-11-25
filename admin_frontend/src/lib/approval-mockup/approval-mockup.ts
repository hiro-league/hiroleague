// mockup: what each app is approved for (Permissions phase 8, "What an app is approved for: the design"). Mock data
// until the core serves an app's approval; the words of each permission are the design's section 8.

/** One thing an app asks to do on its own: a permission, and the app it asks for `apps.ask`. */
export type Ask = {
  permission: string;
  /** The app asked, for apps.ask only. */
  to?: string;
  required: boolean;
  /** One line from the app, for the owner. */
  why: string;
  approved: boolean;
  /** Asked by a new version and not answered yet. */
  waiting: boolean;
};

/** What the owner approves with the app itself. */
export type Identity = { name: string; address: string; lanName: string; port: number };

export type Approval = {
  /** Never answered: the app was just paired. */
  pending: boolean;
  identity: Identity;
  asks: Ask[];
};

/** The owner's words for each permission an app may ask (the design's section 8). */
export const PERMISSION_WORDS: Record<string, string> = {
  'people.see': 'Read the people list: names, WhatsApp numbers, roles',
  'people.notify': 'Notify people on WhatsApp: text, a picture or a voice note',
  'ai.use': 'Ask AI for its jobs, on the profiles you pick',
  'voice.speak': "Make spoken clips in the house's voices",
  'ai.search': "Use the search models: turn texts into vectors and rank them",
  'apps.ask': 'Ask another app for its data',
  'hiro.tell': 'Put text before Hiro when Hiro checks on the apps',
  'people.act': 'Act for the people signed in to it, with their own rights'
};

/** What a permission says to the owner, with the app asked when it names one. */
export function askWords(ask: Ask, appTitle: (name: string) => string = (n) => n): string {
  if (ask.permission === 'apps.ask' && ask.to) return `Ask ${appTitle(ask.to)} for its data`;
  return PERMISSION_WORDS[ask.permission] ?? `${ask.permission} (not understood by this core)`;
}

/** The asks that wait for the owner: every one of a pending app, else the new ones. */
export function waitingAsks(a: Approval): Ask[] {
  return a.asks.filter((x) => a.pending || x.waiting);
}

/** An app waits for the owner when it was never answered or a new version asked for more. */
export const waits = (a: Approval): boolean => a.pending || a.asks.some((x) => x.waiting);

const ask = (permission: string, why: string, extra: Partial<Ask> = {}): Ask => ({
  permission,
  why,
  required: true,
  approved: true,
  waiting: false,
  ...extra
});

/** The new app the mockup adds to the list, paired and waiting for the owner. */
export const MOCK_NEW_APP = {
  extension_id: 'mockup-garden',
  name: 'garden',
  label: 'Garden',
  description: 'Waters the garden, and says when a plant needs care.'
};

/** The mock approvals, by app name: the six apps as the design's map has them, and the new one. */
export const MOCK_APPROVALS: Record<string, Approval> = {
  home: {
    pending: false,
    identity: { name: 'home', address: 'http://home.hiro.local', lanName: 'home.hiro.local', port: 8100 },
    asks: [
      ask('people.see', 'Shows who is home, and whose room is whose'),
      ask('people.notify', 'Tells you when someone arrives, from an automation'),
      ask('ai.use', 'Reads camera pictures and writes automation messages'),
      ask('voice.speak', 'Says alerts aloud on the cameras’ speakers'),
      ask('apps.ask', 'Shows the network’s health on the dashboard', { to: 'net' }),
      ask('hiro.tell', 'Lets Hiro answer who is home'),
      ask('people.act', 'Its Settings pages change people and AI picks, as you'),
      ask('ai.search', 'Finds past camera events by what they show', { required: false, approved: false, waiting: true })
    ]
  },
  net: {
    pending: false,
    identity: { name: 'net', address: 'http://net.hiro.local', lanName: 'net.hiro.local', port: 8130 },
    asks: [
      ask('people.see', 'Knows whose devices are on the network'),
      ask('people.notify', 'Sends its alerts to the people you pick'),
      ask('ai.use', 'Sorts websites into categories'),
      ask('apps.ask', 'Reads the home’s devices and says alerts aloud', { to: 'home' }),
      ask('people.act', 'Its Settings pages change people and AI picks, as you')
    ]
  },
  train: {
    pending: false,
    identity: { name: 'train', address: 'http://train.hiro.local', lanName: 'train.hiro.local', port: 8140 },
    asks: [
      ask('people.see', 'Knows whose face each picture is'),
      ask('people.act', 'Its Settings pages change people, as you')
    ]
  },
  study: {
    pending: false,
    identity: { name: 'study', address: 'http://study.hiro.local', lanName: 'study.hiro.local', port: 8110 },
    asks: [
      ask('people.see', 'Knows which person is which student'),
      ask('ai.use', 'Reads homework pages and marks them'),
      ask('people.act', 'Its Settings pages change people and AI picks, as you')
    ]
  },
  reports: {
    pending: false,
    identity: { name: 'reports', address: 'http://reports.local', lanName: 'reports.local', port: 8120 },
    asks: [
      ask('ai.use', 'Reviews code, reading the checkouts you allow'),
      ask('hiro.tell', 'Lets Hiro answer how the code is doing'),
      ask('people.act', 'Its Settings page picks its AI profile, as you')
    ]
  },
  eval: {
    pending: false,
    identity: { name: 'eval', address: 'http://eval.hiro.local', lanName: 'eval.hiro.local', port: 8150 },
    asks: [
      ask('people.see', 'Names who each test conversation is about'),
      ask('ai.use', 'Runs Hiro’s memory tests'),
      ask('ai.search', 'Searches the test memories as Hiro does'),
      ask('people.act', 'Its Settings pages change people and AI picks, as you')
    ]
  },
  garden: {
    pending: true,
    identity: { name: 'garden', address: 'http://garden.hiro.local', lanName: 'garden.hiro.local', port: 8160 },
    asks: [
      ask('people.see', 'Shows whose plants are whose', { approved: false }),
      ask('people.notify', 'Tells you when a plant needs water', { approved: false }),
      ask('ai.use', 'Names a plant from a photo', { required: false, approved: false }),
      ask('apps.ask', 'Waters only when nobody is in the garden', { to: 'home', required: false, approved: false })
    ]
  }
};
