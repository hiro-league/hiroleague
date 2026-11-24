---
paths:
  - "hiroserver/hirocli/src/hirocli/domain/preferences/**"
  - "hiroserver/hirocli/src/hirocli/runtime/preferences_runtime.py"
  - "admin_frontend/src/lib/features/preferences/**"
  - "admin_frontend/src/lib/api/generated/**"
---

# Adding a `preferences.json` field

A new preference is not done when the backend model has it: it must be **editable in the Preferences admin page** and
must **persist on Save**. Do the whole round trip, in order:

1. **Backend model:** add the field to the right model in `hiroserver/hirocli/src/hirocli/domain/preferences/`
   (`models.py` or the area's `models_*.py`), with `Field(...)` bounds and a default. The PATCH endpoint is
   schema-driven (`preferences_runtime._set_path` walks the pydantic model), so a new field is a valid write path
   automatically: no backend allow-list to update.
2. **Regenerate the frontend types:** from `admin_frontend/`, `npm run gen:prefs-types` (writes
   `src/lib/api/generated/*` from the pydantic models). The check fails when they are stale. API-only computed fields
   (e.g. `*_resolved`) go in `preferences-types.ts`, not the generated file.
3. **The UI control:** an input bound to `ctrl.draft.<section>.<field>` in the right
   `admin_frontend/src/lib/features/preferences/sections/**/*.svelte` card (with `oninput={ctrl.markDirty}` or
   `onchange={ctrl.markDirty}`). **If you're unsure which section or tab it belongs in, ask Michel; don't guess.**
4. **The save:** `editsForSave` diffs the saved copy against the draft using the `/preferences/schema` field metadata
   (`readOnly`, `writeWhole`, `preferencesSaveSkip`, nullable + `model_kind`). A new bound field is picked up
   automatically; don't edit path lists in `shared/preferences-edits-policy.ts`. After changing the save policy, run its
   test (`npx vitest related --run src/lib/features/preferences/shared/preferences-edits-policy.ts`).

Then the one check before the commit (`./scripts/check.sh`, hiro-docs `standards/workflow/check-command.md`). A backend field change needs a
**server restart** to take effect.
