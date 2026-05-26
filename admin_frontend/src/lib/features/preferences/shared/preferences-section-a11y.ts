/** Stable `bodyId` values for collapsible `<SectionCardMuted>` regions in preferences. */
export const PREFERENCES_SECTION_BODY_IDS = {
  modelsChat: 'preferences-section-models-chat',
  modelsStt: 'preferences-section-models-stt',
  modelsTts: 'preferences-section-models-tts',
  modelsTuningProfile: 'preferences-section-models-tuning-profile',
  mediaInput: 'preferences-section-media-input',
  mediaOutput: 'preferences-section-media-output',
  memoryLlm: 'preferences-section-memory-llm',
  memoryEmbedding: 'preferences-section-memory-embedding',
  memoryReranker: 'preferences-section-memory-reranker',
  memoryRetrieval: 'preferences-section-memory-retrieval',
  knowledgeEmbedding: 'preferences-section-knowledge-embedding',
  knowledgeRetrieval: 'preferences-section-knowledge-retrieval',
  knowledgeTuningProfile: 'preferences-section-knowledge-tuning-profile',
  knowledgeAnsweringModel: 'preferences-section-knowledge-answering-model',
  knowledgeRewrite: 'preferences-section-knowledge-rewrite',
  knowledgeAnsweringChunking: 'preferences-section-knowledge-answering-chunking',
  tuningProfilesList: 'preferences-section-tuning-profiles-list'
} as const;
