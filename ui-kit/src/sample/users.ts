// The sample app's words for Settings → Users and Roles ($hiro-app/users).
import type { UsersApp } from '$kit/pages/users/types';

export const USERS: UsersApp = {
	intro: "Everyone here is a person in HiroLeague's family list. They sign in at HiroLeague; Hiro kit keeps no passwords. The role comes from the family list. What a role may do is set under Roles.",
	ways: { web: 'HiroLeague sign-in', dev: 'sign-in off' },
	scope: null
};
