/** Stable `bodyId` values for collapsible `<SectionCardMuted>` regions in preferences. */
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
  graphEngine: 'preferences-section-graph-engine',
  graphEngineReranker: 'preferences-section-graph-engine-reranker',
  graphEngineEval: 'preferences-section-graph-engine-eval',
  graphView: 'preferences-section-graph-view'
} as const;

export function tuningProfileSectionBodyId(profileId: string): string {
  return `preferences-section-tuning-profile-${profileId}`;
}
