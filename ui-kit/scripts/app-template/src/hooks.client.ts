// What the app shows when a page can't be opened (an unknown address, or a throw while SvelteKit
// loads it): a readable message on the error page (routes/+error.svelte). Errors while a page runs
// are caught by the layout (a failed page, or the error bar).
import type { HandleClientError } from '@sveltejs/kit';
import { errorMessage } from '$kit/api/client';

export const handleError: HandleClientError = ({ error, status, message }) => {
	if (status === 404) return { message: 'There is no page at this address.' };
	console.error(error);
	return { message: errorMessage(error) || message };
};
