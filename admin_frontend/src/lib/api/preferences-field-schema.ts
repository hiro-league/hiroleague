import fieldSchemaJson from './generated/preferences-field-schema.json';
import type { PreferencesSchemaMap } from '$lib/features/preferences/shared/preferences-schema';

/** Committed flat field map — mirrors GET /preferences/schema ``fields``. */
export const PREFERENCES_FIELD_SCHEMA = fieldSchemaJson as PreferencesSchemaMap;
