// mockup: Permissions phase 2. Each role's keys in the core's own features while the mockup runs: kept for the whole
// visit (People, then another page, then People again), never sent; a reload starts again from the locked map.
import { CORE_GRANTS_MOCK } from './core-features-mock';

export const coreGrantsMock: Record<string, string[]> = $state({ ...CORE_GRANTS_MOCK });
