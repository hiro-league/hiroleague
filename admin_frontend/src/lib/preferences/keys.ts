export const PREF_KEYS = {
  theme: 'hiro.admin.theme',
  sidebarCollapsed: 'hiro.admin.sidebar.collapsed',
  selectedWorkspace: 'hiro.admin.selectedWorkspace',
  serverActiveTab: 'hiro.admin.server.activeTab',
  channelsDevicesActiveTab: 'hiro.admin.channelsDevices.activeTab',
  chatChannelsActiveTab: 'hiro.admin.chatChannels.activeTab',
  /** "Ask for voice reply" checkbox on Messages tab (local UX preference). */
  chatChannelsVoiceReply: 'hiro.admin.chatChannels.voiceReply',
  /** Show agent token/cost stats on Messages bubbles (default on). */
  chatChannelsShowAgentTelemetry: 'hiro.admin.chatChannels.showAgentTelemetry',
  /** Show agent tool stack on Messages bubbles (default on). */
  chatChannelsShowAgentTools: 'hiro.admin.chatChannels.showAgentTools',
  /** "Use knowledge" per-message toggle on Messages tab (default on). */
  chatChannelsUseKnowledge: 'hiro.admin.chatChannels.useKnowledge',
  /** "Disable tools" per-message toggle on Messages tab (default off ⇒ tools on). */
  chatChannelsDisableTools: 'hiro.admin.chatChannels.disableTools',
  /** Global chat overlay: last open/closed state (Facebook-style pop-anywhere chat). */
  chatOverlayOpen: 'hiro.admin.chatOverlay.open',
  /** Global chat overlay: window mode — full | partial | minimized. */
  chatOverlayMode: 'hiro.admin.chatOverlay.mode',
  catalogActiveTab: 'hiro.admin.catalog.activeTab',
  charactersActiveTab: 'hiro.admin.characters.activeTab',
  knowledgeActiveTab: 'hiro.admin.knowledge.activeTab',
  /** Primary tab on the Memories page: memory facts list vs the entity Graph viz. */
  memoriesActiveTab: 'hiro.admin.memories.activeTab',
  /** Primary tab on the Eval page: memory vs knowledge eval track. */
  evalActiveTab: 'hiro.admin.eval.activeTab',
  /** Primary tab on the Logs page: live log feed vs the Graph runs ledger. */
  logsPrimaryActiveTab: 'hiro.admin.logs.activeTab',
  preferencesActiveTab: 'hiro.admin.preferences.activeTab',
  /** Expanded vs collapsed metric cards row on Graph Runs single-run view (toolbar card always stays). */
  graphRunsRunDetailCardsExpanded: 'hiro.admin.graphRuns.runDetail.cardsExpanded',
  knowledgeLastFolderPrefix: 'hiro.admin.knowledge.lastFolder',
  /** Browse tab: render chunk text as formatted markdown (default on). */
  knowledgeChunkMarkdownFormat: 'hiro.admin.knowledge.chunkMarkdownFormat',
  /** Ask tab: last answer + chunk results, kept across navigation until cleared (sessionStorage). */
  knowledgeAskResult: 'hiro.admin.knowledge.askResult',
  // Phase 5d — cached compare-mode result (parallel to askResult so switching
  // graph mode doesn't blow away the other one's cache on navigation).
  knowledgeAskCompareResult: 'hiro.admin.knowledge.askCompareResult',
  // Phase 5d — last selected graph mode (off/on/compare). Persists across reloads
  // so the user's mode preference survives.
  knowledgeAskGraphMode: 'hiro.admin.knowledge.askGraphMode',
  // Phase 5f — Tab 1 "Also build entity graph (L3)" checkbox preference.
  // Persists so the user's default sticks across uploads.
  knowledgeIngestBuildGraph: 'hiro.admin.knowledge.ingestBuildGraph',
  // Phase 5g — setup-form checkboxes for the Eval Batch (persist defaults
  // across reloads). The eval *run* itself is no longer cached client-side:
  // it's replayed from the server registry (GET /knowledge/eval/state) so the
  // run stays consistent across navigation and across origins (Vite vs packaged).
  knowledgeAskEvalIngest: 'hiro.admin.knowledge.askEvalIngest',
  knowledgeAskEvalBuildGraph: 'hiro.admin.knowledge.askEvalBuildGraph',
  /** Eval corpus-picker folder (the path scanned for corpuses). */
  knowledgeEvalFolder: 'hiro.admin.knowledge.evalFolder',
  /** Eval last-selected corpus id, per track (JSON map { memory, knowledge }). */
  knowledgeEvalCorpus: 'hiro.admin.knowledge.evalCorpus',
  /** Eval: run the optional LLM judge (grade answers vs ideal). */
  knowledgeEvalJudge: 'hiro.admin.knowledge.evalJudge',
  /** Graph tab: the four "Graph options" layout sliders (JSON blob). */
  knowledgeGraphOptions: 'hiro.admin.knowledge.graphOptions',
  /** Graph tab: hidden node types (CSV) — sessionStorage; no URL param (not shareable). */
  knowledgeGraphHideNodes: 'hiro.admin.knowledge.graphHideNodes',
  /** Graph tab: hidden edge types (CSV) — sessionStorage; no URL param (not shareable). */
  knowledgeGraphHideEdges: 'hiro.admin.knowledge.graphHideEdges',
  /** Graph tab: last-viewed partition group_id — sessionStorage; restored on next open. */
  knowledgeGraphActiveGroup: 'hiro.admin.knowledge.graphActiveGroup',
  /** Graph tab: which side the selection/detail aside docks on — 'auto' | 'left' | 'right'.
   *  'auto' (default) follows the chat overlay: left while chat is open (so it isn't
   *  covered), right otherwise. Left/right pin it explicitly. localStorage. */
  knowledgeGraphPanelSide: 'hiro.admin.knowledge.graphPanelSide'
} as const;

export type ThemePreference = 'light' | 'dark';
export type ServerTabPreference = 'workspaces' | 'gateways' | 'metrics';
export type ChannelsDevicesTabPreference = 'channels' | 'devices';
export type ChatChannelsTabPreference = 'channels' | 'messages';
export type ChatOverlayMode = 'full' | 'partial';
export type CatalogTabPreference = 'active-providers' | 'providers' | 'models';
export type CharactersTabPreference = 'browse' | 'detail';
export type KnowledgeTabPreference = 'ingest' | 'browse' | 'ask';
export type MemoriesTabPreference = 'memories' | 'graph';
export type EvalTabPreference = 'memory' | 'knowledge';
export type GraphPanelSidePreference = 'auto' | 'left' | 'right';
export type LogsPrimaryTabPreference = 'logs' | 'runs';
export type PreferencesTabPreference =
  | 'models'
  | 'media'
  | 'knowledge'
  | 'graph-engine'
  | 'agent'
  | 'tuning-profiles';
