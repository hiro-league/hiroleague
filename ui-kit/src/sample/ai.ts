// What an app says on its AI pages ($hiro-app/ai): see pages/ai/types.ts. The sample has no voices (an app without
// `voices` doesn't show the Voices tab).
import type { AiApp } from '$kit/pages/ai/types';

export const AI: AiApp = {
	about: 'The sample app asks an AI for nothing. A real app says here what it asks for; HiroLeague answers, with its AI profiles, budgets and fallbacks.',
	usesAbout: 'What the sample app asks an AI for, and the HiroLeague profile it asks with. Picking one here saves it in HiroLeague.',
	usesNote: '',
	moved: null
};
