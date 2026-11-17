export const PREF_KEYS = {
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
  /** Primary tab on the Logs page: live log feed vs the Graph runs ledger. */
  logsPrimaryActiveTab: 'hiro.admin.logs.activeTab',
  preferencesActiveTab: 'hiro.admin.preferences.activeTab',
  /** Settings page: show fields tagged `advanced` in the schema (default off ⇒ basic only). */
  preferencesShowAdvanced: 'hiro.admin.preferences.showAdvanced',
  /** Expanded vs collapsed metric cards row on Graph Runs single-run view (toolbar card always stays). */
  graphRunsRunDetailCardsExpanded: 'hiro.admin.graphRuns.runDetail.cardsExpanded',
  /** Width (px) of the Graph Runs node detail overlay panel — user-resizable via its left edge. */
  graphRunsNodeDetailWidth: 'hiro.admin.graphRuns.nodeDetail.width',
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
  /** Graph tab: the four "Graph options" layout sliders (JSON blob). */
  knowledgeGraphOptions: 'hiro.admin.knowledge.graphOptions',
  /** Graph tab: hidden node types (CSV) — sessionStorage; no URL param (not shareable). */
  knowledgeGraphHideNodes: 'hiro.admin.knowledge.graphHideNodes',
  /** Graph tab: hidden edge types (CSV) — sessionStorage; no URL param (not shareable). */
  knowledgeGraphHideEdges: 'hiro.admin.knowledge.graphHideEdges',
  /** Graph tab: edge filter MODES (validity / include-undated / max-per-node / by) as a JSON
   *  blob — localStorage. Date ranges are NOT persisted (default to the data's full span). */
  knowledgeGraphEdgeFilters: 'hiro.admin.knowledge.graphEdgeFilters',
  /** Graph tab: last-viewed partition group_id — sessionStorage; restored on next open. */
  knowledgeGraphActiveGroup: 'hiro.admin.knowledge.graphActiveGroup',
  /** Graph tab: selected episode-filter ids, per partition — sessionStorage (survives refresh).
   *  Stored as a JSON map of group_id → chunk_id[] so each partition keeps its own selection. */
  knowledgeGraphEpisodeSel: 'hiro.admin.knowledge.graphEpisodeSel',
  /** Graph tab: which side the selection/detail aside docks on — 'auto' | 'left' | 'right'.
   *  'auto' (default) follows the chat overlay: left while chat is open (so it isn't
   *  covered), right otherwise. Left/right pin it explicitly. localStorage. */
  knowledgeGraphPanelSide: 'hiro.admin.knowledge.graphPanelSide',
  /** Graph tab: collapsed/expanded state of the Graph-options sections (Filters/View/Physics) —
   *  JSON blob, localStorage, so the panel reopens with the same sections folded. */
  knowledgeGraphOptionSections: 'hiro.admin.knowledge.graphOptionSections'
} as const;

export type ServerTabPreference = 'workspaces' | 'gateways' | 'metrics';
export type ChannelsDevicesTabPreference = 'channels' | 'devices';
export type ChatChannelsTabPreference = 'channels' | 'messages';
export type ChatOverlayMode = 'full' | 'partial';
// Merged the former 'active-providers' tab into 'providers' — one providers list shows both
// catalog + configured state, so the separate active tab no longer exists.
// Phase 7a mock-up: 'profiles' (AI profiles) and 'uses' (extension uses → profile).
// 'profiles' | 'voices' | 'embedders' | 'rerankers' | 'uses' are the sub-tabs of the Profiles tab.
export type CatalogTabPreference = 'providers' | 'models' | 'profiles' | 'voices' | 'embedders' | 'rerankers' | 'uses';
export type CharactersTabPreference = 'browse' | 'detail';
export type KnowledgeTabPreference = 'ingest' | 'browse' | 'ask';
export type MemoriesTabPreference = 'memories' | 'graph';
export type GraphPanelSidePreference = 'auto' | 'left' | 'right';
export type LogsPrimaryTabPreference = 'logs' | 'runs' | 'usage';
export type PreferencesTabPreference = 'models' | 'knowledge' | 'graph-engine' | 'agent';
