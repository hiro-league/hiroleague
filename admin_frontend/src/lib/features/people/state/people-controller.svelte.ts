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
import { Action } from '$kit/state/action.svelte';
import { Resource } from '$kit/state/resource.svelte';
import type { Notify } from '$kit/ui/toast.svelte';

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
  const list = new Resource(listPeople);
  const people = $derived(list.data?.people ?? []);
  const roles = $derived(list.data?.roles ?? []);
  /** One action per kind of change; `busy` is any of them, so one button waits for all. */
  const saveFormAction = new Action();
  const saveSignInAction = new Action();
  const removeAction = new Action();
  const removeSignInAction = new Action();
  const busy = $derived(
    saveFormAction.busy || saveSignInAction.busy || removeAction.busy || removeSignInAction.busy
  );

  /** The add/edit dialog: null = closed; editing = null for a new person. */
  let form = $state<PersonFields | null>(null);
  let editing = $state<Person | null>(null);

  /** The sign-in dialog. */
  let signInFor = $state<Person | null>(null);
  let signInName = $state('');
  let password = $state('');
  let passwordAgain = $state('');

  let removeTarget = $state<Person | null>(null);
  let removeSignInTarget = $state<Person | null>(null);

  function roleName(roleId: string): string {
    return roles.find((r) => r.role_id === roleId)?.name ?? roleId;
  }

  function openAdd() {
    editing = null;
    form = { ...EMPTY };
    saveFormAction.clear();
  }

  function openEdit(person: Person) {
    editing = person;
    form = {
      name: person.name,
      role_id: person.role_id,
      calls_them: person.calls_them,
      whatsapp: shownNumber(person.whatsapp)
    };
    saveFormAction.clear();
  }

  function closeForm() {
    if (busy) return;
    form = null;
    editing = null;
  }

  async function saveForm() {
    if (!form) return;
    const fields = form;
    const person = editing;
    await saveFormAction.run(async () => {
      if (person) {
        await updatePerson(person.person_id, fields);
        notify('success', `Saved ${fields.name}.`);
      } else {
        await addPerson(fields);
        notify('success', `Added ${fields.name}.`);
      }
      form = null;
      editing = null;
      await list.reload();
    });
  }

  function openSignIn(person: Person) {
    signInFor = person;
    signInName = person.sign_in ?? person.name.split(' ')[0].toLowerCase();
    password = '';
    passwordAgain = '';
    saveSignInAction.clear();
  }

  function closeSignIn() {
    if (busy) return;
    signInFor = null;
  }

  async function saveSignIn() {
    if (!signInFor) return;
    const person = signInFor;
    const same = password === passwordAgain;
    await saveSignInAction.run(async () => {
      if (!same) throw new Error("The two passwords aren't the same.");
      await setSignIn(person.person_id, signInName.trim(), password);
      notify('success', `${person.name} signs in as ${signInName.trim()}.`);
      signInFor = null;
      await list.reload();
    });
    if (same) {
      password = '';
      passwordAgain = '';
    }
  }

  async function submitRemoveSignIn() {
    if (!removeSignInTarget) return;
    const person = removeSignInTarget;
    await removeSignInAction.run(async () => {
      await removeSignIn(person.person_id);
      notify('success', `${person.name} no longer signs in to the admin.`);
      removeSignInTarget = null;
      await list.reload();
    });
    if (removeSignInAction.error) notify('error', removeSignInAction.error);
  }

  async function submitRemove() {
    if (!removeTarget) return;
    const person = removeTarget;
    await removeAction.run(async () => {
      await removePerson(person.person_id);
      notify('success', `Removed ${person.name}.`);
      removeTarget = null;
      await list.reload();
    });
    if (removeAction.error) notify('error', removeAction.error);
  }

  return {
    get people() {
      return people;
    },
    get roles() {
      return roles;
    },
    get loading() {
      return list.data === null && !list.error;
    },
    get busy() {
      return busy;
    },
    get error() {
      return list.error || null;
    },
    get form() {
      return form;
    },
    get editing() {
      return editing;
    },
    get formError() {
      return saveFormAction.error || null;
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
      return saveSignInAction.error || null;
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
    load: list.reload,
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
