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
  catalogActiveTab: 'hiro.admin.catalog.activeTab',
  charactersActiveTab: 'hiro.admin.characters.activeTab',
  knowledgeActiveTab: 'hiro.admin.knowledge.activeTab',
  /** Primary pill on Graph Runs page: workspace runs ledger vs Mem0 memories pane. */
  graphRunsActiveTab: 'hiro.admin.graphRuns.activeTab',
  /** Expanded vs collapsed metric cards row on Graph Runs single-run view (toolbar card always stays). */
  graphRunsRunDetailCardsExpanded: 'hiro.admin.graphRuns.runDetail.cardsExpanded',
  knowledgeLastFolderPrefix: 'hiro.admin.knowledge.lastFolder',
  /** Browse tab: render chunk text as formatted markdown (default on). */
  knowledgeChunkMarkdownFormat: 'hiro.admin.knowledge.chunkMarkdownFormat'
} as const;

export type ThemePreference = 'light' | 'dark';
export type ServerTabPreference = 'workspaces' | 'gateways' | 'metrics';
export type ChannelsDevicesTabPreference = 'channels' | 'devices';
export type ChatChannelsTabPreference = 'channels' | 'messages';
export type CatalogTabPreference = 'providers' | 'models';
export type CharactersTabPreference = 'browse' | 'detail';
export type KnowledgeTabPreference = 'ingest' | 'browse' | 'ask';
export type GraphRunsPrimaryTabPreference = 'runs' | 'memories';
