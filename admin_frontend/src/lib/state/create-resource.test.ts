import { describe, expect, it, vi } from 'vitest';

vi.mock('$lib/runtime/feature-errors', () => ({
  featureErrorFrom: (err: unknown, fallback = 'Request failed.') => {
    if (err instanceof Error) return err.message;
    return fallback;
  }
}));

import { createListResource, createListSelection, createMutation, createResource } from './create-resource.svelte';

describe('createResource', () => {
  it('loads data on success', async () => {
    const loader = vi.fn().mockResolvedValue(['a']);
    const resource = createResource(loader, { initial: [] as string[] });

    await resource.load();

    expect(loader).toHaveBeenCalledTimes(1);
    expect(resource.data).toEqual(['a']);
    expect(resource.loading).toBe(false);
    expect(resource.error).toBeNull();
    expect(resource.loaded).toBe(true);
  });

  it('sets error on failure without clearing existing data', async () => {
    const loader = vi
      .fn()
      .mockResolvedValueOnce(['keep'])
      .mockRejectedValueOnce(new Error('network down'));
    const resource = createResource(loader, { initial: [] as string[], errorPrefix: 'Failed.' });

    await resource.load();
    await resource.load({ silent: true });

    expect(resource.data).toEqual(['keep']);
    expect(resource.error).toBe('network down');
    expect(resource.loading).toBe(false);
  });

  it('silent refresh does not toggle loading', async () => {
    let resolveSecond!: (value: string[]) => void;
    const second = new Promise<string[]>((resolve) => {
      resolveSecond = resolve;
    });
    const loader = vi.fn().mockResolvedValueOnce(['x']).mockReturnValueOnce(second);
    const resource = createResource(loader, { initial: [] as string[] });

    await resource.load();
    expect(resource.loading).toBe(false);

    const pending = resource.load({ silent: true });
    expect(resource.loading).toBe(false);

    resolveSecond(['y']);
    await pending;
    expect(resource.data).toEqual(['y']);
    expect(resource.loading).toBe(false);
  });

  it('reset restores initial state', async () => {
    const resource = createResource(vi.fn().mockResolvedValue(['z']), { initial: [] as string[] });
    await resource.load();
    resource.reset();
    expect(resource.data).toEqual([]);
    expect(resource.error).toBeNull();
    expect(resource.loaded).toBe(false);
  });

  it('replace sets data and clears error', async () => {
    const resource = createResource(vi.fn().mockRejectedValue(new Error('fail')), {
      initial: [] as string[]
    });
    await resource.load();
    resource.replace(['fresh']);
    expect(resource.data).toEqual(['fresh']);
    expect(resource.error).toBeNull();
  });
});

describe('createListSelection', () => {
  type Row = { id: string; label: string };

  it('clears selection when the row disappears from candidates', () => {
    const selection = createListSelection<Row>({ getId: (row) => row.id });
    selection.setCandidates([
      { id: '1', label: 'one' },
      { id: '2', label: 'two' }
    ]);
    selection.select('1');
    selection.setCandidates([{ id: '2', label: 'two' }]);
    selection.reconcile();
    expect(selection.selectedId).toBeNull();
  });
});

describe('createListResource', () => {
  type Row = { id: string; label: string };

  it('reconcileSelection clears a missing row and keeps a present one', async () => {
    const rows: Row[] = [
      { id: '1', label: 'one' },
      { id: '2', label: 'two' }
    ];
    const loader = vi
      .fn()
      .mockResolvedValueOnce(rows)
      .mockResolvedValueOnce([{ id: '2', label: 'two' }])
      .mockResolvedValueOnce([{ id: '2', label: 'two' }]);
    const list = createListResource<Row>(loader, { getId: (row) => row.id });

    await list.load();
    list.select('1');
    await list.load({ silent: true });

    expect(list.selectedId).toBeNull();
    expect(list.selected).toBeNull();

    list.select('2');
    await list.load({ silent: true });
    expect(list.selectedId).toBe('2');
    expect(list.selected).toEqual({ id: '2', label: 'two' });
  });
});

describe('createMutation', () => {
  it('notifies success, runs onDone, and toggles busy', async () => {
    const notify = vi.fn();
    const fn = vi.fn().mockResolvedValue({ id: 7 });
    const onDone = vi.fn();
    const mutation = createMutation(fn, {
      notify,
      successMsg: (result) => `done ${result.id}`,
      onDone
    });

    expect(mutation.busy).toBe(false);
    const pending = mutation.run('arg' as never);
    expect(mutation.busy).toBe(true);
    await pending;
    expect(mutation.busy).toBe(false);
    expect(notify).toHaveBeenCalledWith('success', 'done 7');
    expect(onDone).toHaveBeenCalledWith({ id: 7 });
  });

  it('notifies error with prefix fallback', async () => {
    const notify = vi.fn();
    const mutation = createMutation(vi.fn().mockRejectedValue('nope'), {
      notify,
      errorPrefix: 'Save failed.'
    });

    await mutation.run();
    expect(notify).toHaveBeenCalledWith('error', 'Save failed.');
  });
});
