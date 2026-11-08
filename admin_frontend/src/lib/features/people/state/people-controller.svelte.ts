import {
  addPerson,
  listPeople,
  removePerson,
  removeSignIn,
  setSignIn,
  updatePerson,
  type Person,
  type PersonFields,
  type Role
} from '$lib/api/people';
import type { Notify } from '$lib/ui/toast-types';

export type PeopleController = ReturnType<typeof createPeopleController>;

/** A WhatsApp number as people read it: "+" and the digits. */
export function shownNumber(digits: string): string {
  return digits ? `+${digits}` : '';
}

const EMPTY: PersonFields = { name: '', role_id: 'adult', calls_them: '', whatsapp: '' };

/**
 * People page state (Phase 6): the family list, adding and editing a person, their
 * admin sign-in, and removing them. The server refuses what would lock everyone out
 * (the only Owner, the only sign-in) and says why.
 */
export function createPeopleController(notify: Notify) {
  let people = $state<Person[]>([]);
  let roles = $state<Role[]>([]);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state<string | null>(null);

  /** The add/edit dialog: null = closed; editing = null for a new person. */
  let form = $state<PersonFields | null>(null);
  let editing = $state<Person | null>(null);
  let formError = $state<string | null>(null);

  /** The sign-in dialog. */
  let signInFor = $state<Person | null>(null);
  let signInName = $state('');
  let password = $state('');
  let passwordAgain = $state('');
  let signInError = $state<string | null>(null);

  let removeTarget = $state<Person | null>(null);
  let removeSignInTarget = $state<Person | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const data = (await listPeople()).data;
      people = data.people;
      roles = data.roles;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load the family list.';
    } finally {
      loading = false;
    }
  }

  function roleName(roleId: string): string {
    return roles.find((r) => r.role_id === roleId)?.name ?? roleId;
  }

  function openAdd() {
    editing = null;
    form = { ...EMPTY };
    formError = null;
  }

  function openEdit(person: Person) {
    editing = person;
    form = {
      name: person.name,
      role_id: person.role_id,
      calls_them: person.calls_them,
      whatsapp: shownNumber(person.whatsapp)
    };
    formError = null;
  }

  function closeForm() {
    if (busy) return;
    form = null;
    editing = null;
  }

  async function saveForm() {
    if (!form) return;
    busy = true;
    formError = null;
    try {
      if (editing) {
        await updatePerson(editing.person_id, form);
        notify('success', `Saved ${form.name}.`);
      } else {
        await addPerson(form);
        notify('success', `Added ${form.name}.`);
      }
      form = null;
      editing = null;
      await load();
    } catch (err) {
      formError = err instanceof Error ? err.message : 'Saving failed.';
    } finally {
      busy = false;
    }
  }

  function openSignIn(person: Person) {
    signInFor = person;
    signInName = person.sign_in ?? person.name.split(' ')[0].toLowerCase();
    password = '';
    passwordAgain = '';
    signInError = null;
  }

  function closeSignIn() {
    if (busy) return;
    signInFor = null;
  }

  async function saveSignIn() {
    if (!signInFor) return;
    if (password !== passwordAgain) {
      signInError = "The two passwords aren't the same.";
      return;
    }
    busy = true;
    signInError = null;
    try {
      await setSignIn(signInFor.person_id, signInName.trim(), password);
      notify('success', `${signInFor.name} signs in as ${signInName.trim()}.`);
      signInFor = null;
      await load();
    } catch (err) {
      signInError = err instanceof Error ? err.message : 'Saving the sign-in failed.';
    } finally {
      busy = false;
      password = '';
      passwordAgain = '';
    }
  }

  async function submitRemoveSignIn() {
    if (!removeSignInTarget) return;
    busy = true;
    try {
      await removeSignIn(removeSignInTarget.person_id);
      notify('success', `${removeSignInTarget.name} no longer signs in to the admin.`);
      removeSignInTarget = null;
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Removing the sign-in failed.');
    } finally {
      busy = false;
    }
  }

  async function submitRemove() {
    if (!removeTarget) return;
    busy = true;
    try {
      await removePerson(removeTarget.person_id);
      notify('success', `Removed ${removeTarget.name}.`);
      removeTarget = null;
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Remove failed.');
    } finally {
      busy = false;
    }
  }

  return {
    get people() {
      return people;
    },
    get roles() {
      return roles;
    },
    get loading() {
      return loading;
    },
    get busy() {
      return busy;
    },
    get error() {
      return error;
    },
    get form() {
      return form;
    },
    get editing() {
      return editing;
    },
    get formError() {
      return formError;
    },
    get signInFor() {
      return signInFor;
    },
    get signInName() {
      return signInName;
    },
    set signInName(value: string) {
      signInName = value;
    },
    get password() {
      return password;
    },
    set password(value: string) {
      password = value;
    },
    get passwordAgain() {
      return passwordAgain;
    },
    set passwordAgain(value: string) {
      passwordAgain = value;
    },
    get signInError() {
      return signInError;
    },
    get removeTarget() {
      return removeTarget;
    },
    set removeTarget(value: Person | null) {
      if (!busy) removeTarget = value;
    },
    get removeSignInTarget() {
      return removeSignInTarget;
    },
    set removeSignInTarget(value: Person | null) {
      if (!busy) removeSignInTarget = value;
    },
    load,
    roleName,
    openAdd,
    openEdit,
    closeForm,
    saveForm,
    openSignIn,
    closeSignIn,
    saveSignIn,
    submitRemove,
    submitRemoveSignIn
  };
}
