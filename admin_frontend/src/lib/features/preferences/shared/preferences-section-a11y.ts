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
  // Graph-engine tab: each model/profile and the retrieval-agent prompt live in their own
  // collapsible section (so they need their own stable body ids). `graphEvalModels` now holds the
  // retrieval-agent model/profile (eval answer/judge models moved to the Eval tab).
  graphExtraction: 'preferences-section-graph-extraction',
  graphEvalModels: 'preferences-section-graph-eval-models',
  graphEngine: 'preferences-section-graph-engine',
  graphEngineReranker: 'preferences-section-graph-engine-reranker',
  graphView: 'preferences-section-graph-view',
  graphRetrievalAgent: 'preferences-section-graph-retrieval-agent',
  graphEvalRetrievalAgentPrompt: 'preferences-section-graph-eval-retrieval-agent-prompt',
  // Eval tab: answer/judge models + the mem-eval answer/judge prompts.
  evalModels: 'preferences-section-eval-models',
  evalMemAnswerPrompt: 'preferences-section-eval-mem-answer-prompt',
  evalJudgePrompt: 'preferences-section-eval-judge-prompt'
} as const;

export function tuningProfileSectionBodyId(profileId: string): string {
  return `preferences-section-tuning-profile-${profileId}`;
}
