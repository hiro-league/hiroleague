import { describe, expect, it, vi } from 'vitest';
import { Draft, Drafts } from './draft.svelte';
import { KeyedAction } from './keyed-action.svelte';

type Form = { name: string; tags: string[] };
const saved: Form = { name: 'Hall', tags: ['a'] };

describe('Draft', () => {
	it('is clean until edited, and again after undo', () => {
		const d = new Draft<Form>({ name: '', tags: [] }, { guard: false });
		d.load(saved);
		expect(d.dirty).toBe(false);
		d.value.tags.push('b');
		expect(d.dirty).toBe(true);
		d.undo();
		expect(d.dirty).toBe(false);
		expect(d.value).toEqual(saved);
	});

	it('does not share objects with what is saved', () => {
		const d = new Draft<Form>({ name: '', tags: [] }, { guard: false });
		d.load(saved);
		d.value.tags.push('x');
		expect(d.saved?.tags).toEqual(['a']);
		expect(saved.tags).toEqual(['a']);
	});

	it('an unedited draft follows a newer saved value, an edited one keeps its edits', () => {
		const d = new Draft<Form>({ name: '', tags: [] }, { guard: false });
		d.load(saved);
		d.load({ name: 'Kitchen', tags: [] });
		expect(d.value.name).toBe('Kitchen');
		d.value.name = 'Mine';
		d.load({ name: 'Cellar', tags: [] });
		expect(d.value.name).toBe('Mine');
		expect(d.saved?.name).toBe('Cellar');
		d.load({ name: 'Attic', tags: [] }, true);
		expect(d.value.name).toBe('Attic');
	});

	it('is dirty against its blank start while nothing is saved', () => {
		const d = new Draft<Form>({ name: '', tags: [] }, { guard: false });
		expect(d.dirty).toBe(false);
		d.value.name = 'New';
		expect(d.dirty).toBe(true);
	});

	it('saves, takes the answer as what is saved, and is clean', async () => {
		const save = vi.fn(async (f: Form) => ({ ...f, name: f.name.toUpperCase() }));
		const d = new Draft<Form>({ name: '', tags: [] }, { save, guard: false });
		d.load(saved);
		d.value.name = 'lounge';
		expect(await d.save()).toBe(true);
		expect(save).toHaveBeenCalledWith({ name: 'lounge', tags: ['a'] });
		expect(d.saved?.name).toBe('LOUNGE');
		expect(d.value.name).toBe('LOUNGE');
		expect(d.dirty).toBe(false);
	});

	it('keeps the edits and says what went wrong when a save fails', async () => {
		const d = new Draft<Form>({ name: '', tags: [] }, { save: async () => Promise.reject(new Error('offline')), guard: false });
		d.load(saved);
		d.value.name = 'lounge';
		expect(await d.save()).toBe(false);
		expect(d.action.error).toBe('offline');
		expect(d.dirty).toBe(true);
		expect(d.value.name).toBe('lounge');
	});

	it('uses its own equality when given', () => {
		const d = new Draft<number[]>([], { guard: false, equal: (a, b) => a.length === b.length });
		d.load([1, 2]);
		d.value = [9, 9];
		expect(d.dirty).toBe(false);
	});
});

describe('Drafts', () => {
	it('keeps one draft per key and knows when any is edited', () => {
		const all = new Drafts<Form>(() => new Draft<Form>({ name: '', tags: [] }, { guard: false }), { guard: false });
		all.of('a').load(saved);
		all.of('b').load(saved);
		expect(all.dirty).toBe(false);
		all.of('b').value.name = 'edited';
		expect(all.dirty).toBe(true);
		expect(all.isDirty('a')).toBe(false);
		expect(all.isDirty('b')).toBe(true);
		expect(all.isDirty('never made')).toBe(false);
		all.forget('b');
		expect(all.dirty).toBe(false);
	});
});

describe('KeyedAction', () => {
	it('is busy for one key only, and keeps each key\'s error', async () => {
		const run = new KeyedAction();
		let release!: () => void;
		const slow = run.run('a', () => new Promise<void>((r) => (release = r)));
		expect(run.busy('a')).toBe(true);
		expect(run.busy('b')).toBe(false);
		expect(run.anyBusy).toBe(true);
		await run.run('b', async () => Promise.reject(new Error('nope')));
		expect(run.error('b')).toBe('nope');
		expect(run.error('a')).toBe('');
		release();
		await slow;
		expect(run.busy('a')).toBe(false);
		expect(run.anyBusy).toBe(false);
	});

	it('says what a run did, and runs `then` after a good one', async () => {
		const then = vi.fn();
		const run = new KeyedAction({ then });
		await run.run('a', async () => 'Saved 3');
		expect(run.result('a')).toEqual({ text: 'Saved 3', error: false });
		expect(then).toHaveBeenCalledWith('a');
		await run.run('a', async () => Promise.reject(new Error('bad')));
		expect(run.result('a')).toEqual({ text: 'bad', error: true });
		expect(then).toHaveBeenCalledTimes(1);
		run.clear('a');
		expect(run.result('a')).toBeNull();
	});
});
