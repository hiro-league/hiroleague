export const PREF_KEYS = {
  theme: 'hiro.admin.theme',
  sidebarCollapsed: 'hiro.admin.sidebar.collapsed',
  selectedWorkspace: 'hiro.admin.selectedWorkspace',
  serverActiveTab: 'hiro.admin.server.activeTab',
  channelsDevicesActiveTab: 'hiro.admin.channelsDevices.activeTab',
  chatChannelsActiveTab: 'hiro.admin.chatChannels.activeTab',
  /** "Ask for voice reply" checkbox on Messages tab (local UX preference). */
  chatChannelsVoiceReply: 'hiro.admin.chatChannels.voiceReply',
  /** Show agent tool stack + token counts on Messages tab (default on). */
  chatChannelsShowAgentTelemetry: 'hiro.admin.chatChannels.showAgentTelemetry',
  /** "Use knowledge" per-message toggle on Messages tab (default on). */
  chatChannelsUseKnowledge: 'hiro.admin.chatChannels.useKnowledge',
  catalogActiveTab: 'hiro.admin.catalog.activeTab',
  charactersActiveTab: 'hiro.admin.characters.activeTab',
  knowledgeActiveTab: 'hiro.admin.knowledge.activeTab',
  /** Primary pill on Graph Runs page: workspace runs ledger vs Mem0 memories pane. */
  graphRunsActiveTab: 'hiro.admin.graphRuns.activeTab',
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
  knowledgeAskEvalBuildGraph: 'hiro.admin.knowledge.askEvalBuildGraph'
} as const;

export type ThemePreference = 'light' | 'dark';
export type ServerTabPreference = 'workspaces' | 'gateways' | 'metrics';
export type ChannelsDevicesTabPreference = 'channels' | 'devices';
export type ChatChannelsTabPreference = 'channels' | 'messages';
export type CatalogTabPreference = 'active-providers' | 'providers' | 'models';
export type CharactersTabPreference = 'browse' | 'detail';
export type KnowledgeTabPreference = 'ingest' | 'browse' | 'ask' | 'graph';
export type GraphRunsPrimaryTabPreference = 'runs' | 'memories';
export type PreferencesTabPreference =
  | 'models'
  | 'media'
  | 'memory'
  | 'knowledge'
  | 'agent'
  | 'tuning-profiles';
