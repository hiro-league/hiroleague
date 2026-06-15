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
  // Graph-engine tab: each model/profile and each eval prompt now lives in its own collapsible
  // section (so they need their own stable body ids).
  graphExtraction: 'preferences-section-graph-extraction',
  graphEvalModels: 'preferences-section-graph-eval-models',
  graphEngine: 'preferences-section-graph-engine',
  graphEngineReranker: 'preferences-section-graph-engine-reranker',
  graphView: 'preferences-section-graph-view',
  graphEvalMemAnswerPrompt: 'preferences-section-graph-eval-mem-answer-prompt',
  graphEvalJudgePrompt: 'preferences-section-graph-eval-judge-prompt',
  graphEvalKnowledgePrompt: 'preferences-section-graph-eval-knowledge-prompt'
} as const;

export function tuningProfileSectionBodyId(profileId: string): string {
  return `preferences-section-tuning-profile-${profileId}`;
}
