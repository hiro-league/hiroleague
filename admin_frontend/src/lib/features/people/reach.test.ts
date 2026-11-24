import { describe, expect, it } from 'vitest';
import { featureSummary, inRoleOrder, reachOf, setReach, withReaches } from './reach';

describe('reachOf', () => {
  it('reads the plain key as everyone, :own as their own', () => {
    const keys = new Set(['people.see', 'people.edit:own']);
    expect(reachOf(keys, 'people.see')).toBe('all');
    expect(reachOf(keys, 'people.edit')).toBe('own');
    expect(reachOf(keys, 'automations.see')).toBe('no');
  });
});

describe('setReach', () => {
  const rights = ['see', 'build', 'run'];

  it('raises see to the reach of the right granted', () => {
    expect(setReach(rights, {}, 'build', 'own')).toEqual({ see: 'own', build: 'own', run: 'no' });
    expect(setReach(rights, { see: 'own', build: 'own' }, 'run', 'all')).toEqual({ see: 'all', build: 'own', run: 'all' });
  });

  it('keeps see when it already reaches as far', () => {
    expect(setReach(rights, { see: 'all' }, 'build', 'own')).toEqual({ see: 'all', build: 'own', run: 'no' });
  });

  it('lowers every other right when see is lowered', () => {
    expect(setReach(rights, { see: 'all', build: 'all', run: 'own' }, 'see', 'own')).toEqual({ see: 'own', build: 'own', run: 'own' });
    expect(setReach(rights, { see: 'all', build: 'own' }, 'see', 'no')).toEqual({ see: 'no', build: 'no', run: 'no' });
  });

  it('leaves a feature without see alone', () => {
    expect(setReach(['use'], {}, 'use', 'own')).toEqual({ use: 'own' });
  });
});

describe('featureSummary', () => {
  const rights = [
    { id: 'see', name: 'See' },
    { id: 'build', name: 'Build' }
  ];

  it('says nothing, everything, or each right with its reach', () => {
    expect(featureSummary(rights, {})).toBe('—');
    expect(featureSummary(rights, { see: 'all', build: 'all' })).toBe('Everything');
    expect(featureSummary(rights, { see: 'own', build: 'own' })).toBe('Everything, their own');
    expect(featureSummary(rights, { see: 'all', build: 'own' })).toBe('See, Build (their own)');
    expect(featureSummary(rights, { see: 'own' })).toBe('See (their own)');
  });
});

describe('withReaches', () => {
  it("replaces one feature's keys and keeps the others", () => {
    const keys = ['auto.see', 'auto.build:own', 'streams.see'];
    expect(withReaches(keys, 'auto', { see: 'own', build: 'all', run: 'no' })).toEqual([
      'streams.see',
      'auto.see:own',
      'auto.build'
    ]);
    expect(withReaches(keys, 'auto', { see: 'no', build: 'no' })).toEqual(['streams.see']);
  });
});

describe('inRoleOrder', () => {
  it('puts the roles in the roles order, owner first, once each', () => {
    expect(inRoleOrder(['kid', 'adult', 'owner', 'kid'], ['owner', 'adult', 'kid'])).toEqual(['owner', 'adult', 'kid']);
  });

  it('puts a role it does not know last', () => {
    expect(inRoleOrder(['gone', 'kid'], ['owner', 'adult', 'kid'])).toEqual(['kid', 'gone']);
  });
});
