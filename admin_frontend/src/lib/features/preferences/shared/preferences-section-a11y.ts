/** Stable `bodyId` values for collapsible `<Section>` regions in preferences. */
export const PREFERENCES_SECTION_BODY_IDS = {
  modelsChat: 'preferences-section-models-chat',
  modelsStt: 'preferences-section-models-stt',
  modelsTts: 'preferences-section-models-tts',
  mediaInput: 'preferences-section-media-input',
  mediaOutput: 'preferences-section-media-output',
  agentChatSettings: 'preferences-section-agent-chat-settings',
  agentChatInstructions: 'preferences-section-agent-chat-instructions',
  // "Agent memory" card, now on the Agent tab (was the removed Agent Memory tab).
  memoryRetrieval: 'preferences-section-memory-retrieval',
  knowledgeEmbedding: 'preferences-section-knowledge-embedding',
  knowledgeRetrieval: 'preferences-section-knowledge-retrieval',
  knowledgeReranker: 'preferences-section-knowledge-reranker',
  knowledgeAnsweringModel: 'preferences-section-knowledge-answering-model',
  knowledgeRewrite: 'preferences-section-knowledge-rewrite',
  knowledgeGraphBackend: 'preferences-section-knowledge-graph-backend',
  // Graph-engine tab: each card lives in its own collapsible section (so they need their own
  // stable body ids).
  graphExtraction: 'preferences-section-graph-extraction',
  graphEngine: 'preferences-section-graph-engine',
  graphEngineReranker: 'preferences-section-graph-engine-reranker',
  graphView: 'preferences-section-graph-view',
  // Chat memory retrieval-agent cards (memory.retrieval.*) on the Memory (graph-engine) tab.
  memoryRetrievalModels: 'preferences-section-memory-retrieval-models',
  memoryRetrievalCaps: 'preferences-section-memory-retrieval-caps'
} as const;
