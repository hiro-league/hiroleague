/** Async resource state shared by `createResource` / `createListResource`. */
export interface Resource<T> {
  readonly data: T;
  readonly loading: boolean;
  readonly error: string | null;
  /** True once the first `load()` settles (success or failure). */
  readonly loaded: boolean;
  load(opts?: { silent?: boolean }): Promise<T>;
  /** Replace data without a network round-trip (e.g. after a mutation that already fetched). */
  replace(value: T): void;
  reset(): void;
}
