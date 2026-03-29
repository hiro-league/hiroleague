---
name: LLM Catalog Phase 3c
overview: "Implement Phase 3c of the LLM Catalog: add `recommended_models` to the Provider schema, populate catalog.yaml with editorial defaults, and wire onboarding auto-fill into the CLI so workspaces get usable default models immediately after credential provisioning."
todos:
  - id: schema
    content: Add `recommended_models` field to Provider model, CatalogDocument validator, and `suggested_defaults()` to ModelCatalog
    status: pending
  - id: catalog-yaml
    content: Populate `recommended_models` for all 6 providers in catalog.yaml
    status: pending
  - id: schema-tests
    content: Unit tests for validator (rejects bad refs) and `suggested_defaults()` return values
    status: pending
  - id: defaults-logic
    content: Implement `compute_suggested_defaults()` and `apply_defaults()` domain helpers with DefaultSuggestion dataclass
    status: pending
  - id: defaults-tests
    content: "Unit tests for defaults computation: empty slots, skip set slots, multi-provider precedence, unavailable filtering"
    status: pending
  - id: cli-interactive
    content: Wire defaults into `interactive_credential_provisioning` with Y/n/pick prompt
    status: pending
  - id: cli-provider-add
    content: Wire defaults into `provider add` command after successful key storage
    status: pending
  - id: cli-scan-env
    content: Wire defaults into `provider scan-env --import-keys` after import
    status: pending
  - id: cli-setup-noninteractive
    content: Silent auto-fill in `SetupTool.execute()` non-interactive path
    status: pending
  - id: cli-suggest-defaults
    content: New `hirocli provider suggest-defaults` standalone command
    status: pending
  - id: cli-tests
    content: Tests for CLI integration points (prompt rendering, non-interactive apply, suggest-defaults edge cases)
    status: pending
  - id: mintdocs
    content: Review and update mintdocs if setup flow output or provider docs changed
    status: pending
isProject: false
---

# Phase 3c -- Catalog Defaults and Onboarding Auto-fill

**Project mode:** initial development -- no backward compatibility required.

## Current State

- **Provider model** ([model_catalog.py](hiroserver/hirocli/src/hirocli/domain/model_catalog.py)) has no `recommended_models` field.
- **CatalogDocument** has a `cross_reference_providers` validator (provider IDs and replacement IDs) but no recommended-model validation.
- **ModelCatalog** has no `suggested_defaults()` method.
- **catalog.yaml** ([catalog.yaml](hiroserver/hirocli/src/hirocli/catalog_data/catalog.yaml)) has 6 providers and ~20 models; no `recommended_models` entries.
- **interactive_credential_provisioning** ([provider.py](hiroserver/hirocli/src/hirocli/commands/provider.py)) ends with `print_provider_summary_table` -- no default suggestion step.
- **provider add** and **scan-env** CLI commands store credentials and print results -- no follow-up defaults flow.

---

## Part 1: Catalog Schema and Service

### 1a. Add `recommended_models` to Provider

In [model_catalog.py](hiroserver/hirocli/src/hirocli/domain/model_catalog.py), add to the `Provider` model:

```python
recommended_models: dict[ModelKind, str] | None = None
```

This is a `dict` mapping model kind (e.g. `"chat"`, `"tts"`) to canonical model ID (e.g. `"openai:gpt-5.4"`). Default `None` (not all providers need recommendations).

### 1b. Add CatalogDocument validator

Extend the existing `cross_reference_providers` validator (or add a new one) on `CatalogDocument` to validate:

- Each recommended model ID must exist in the catalog models list.
- Each recommended model must belong to the declaring provider (ID prefix match).
- Each recommended model's `model_kind` must match the dict key.

### 1c. Add `ModelCatalog.suggested_defaults()`

```python
def suggested_defaults(self, provider_id: str) -> dict[str, str]:
    """Return provider's recommended_models map (kind -> canonical ID). Empty dict if none."""
```

Simple lookup on the provider's `recommended_models` field.

### 1d. Populate catalog.yaml

Add `recommended_models` to each provider based on the existing models:

- **openai**: `{chat: openai:gpt-5.4, tts: openai:gpt-4o-mini-tts, stt: openai:gpt-4o-transcribe, embedding: openai:text-embedding-3-small}`
- **google**: `{chat: google:gemini-2.5-flash, embedding: google:gemini-embedding-001}`
- **anthropic**: `{chat: anthropic:claude-sonnet-4-6}`
- **ollama**: `{chat: ollama:llama3.3, embedding: ollama:nomic-embed-text}`
- **lm_studio**: `{chat: lm_studio:local-model}`
- **jan**: `{chat: jan:local-model}`

### 1e. Unit tests

In an existing or new test file alongside `model_catalog.py` tests:

- Validator rejects recommended model with wrong provider prefix.
- Validator rejects recommended model with wrong kind.
- Validator rejects recommended model ID not in catalog.
- `suggested_defaults()` returns correct map for a provider.
- `suggested_defaults()` returns empty dict for a provider with no recommendations.
- `suggested_defaults()` returns empty dict for unknown provider ID.

---

## Part 2: Default Suggestion Logic (domain helper)

### 2a. Create `suggest_and_apply_defaults()` helper

Add a new function in [preferences.py](hiroserver/hirocli/src/hirocli/domain/preferences.py) (or a small new module `domain/onboarding_defaults.py` if preferred for separation):

```python
@dataclass
class DefaultSuggestion:
    kind: str            # "chat", "tts", "stt", "summarization"
    model_id: str        # canonical ID
    display_name: str
    provider_id: str
    provider_display_name: str

def compute_suggested_defaults(
    provider_ids: list[str],
    catalog: ModelCatalog,
    available: AvailableModelsService,
    current_prefs: LLMPreferences,
) -> list[DefaultSuggestion]:
    """Collect catalog-recommended defaults for given providers, filtered to available models,
    only for preference slots that are currently empty. First provider wins per kind."""

def apply_defaults(
    prefs: WorkspacePreferences,
    suggestions: list[DefaultSuggestion],
) -> list[DefaultSuggestion]:
    """Apply suggestions to empty preference slots. Returns list of actually applied suggestions."""
```

Key logic:

- Iterate `provider_ids` in order (first configured wins for each kind).
- For each provider, get `catalog.suggested_defaults(pid)`.
- For each kind/model_id pair, check `available.is_model_available(model_id)`.
- Map kind to preference attribute: `chat -> default_chat`, `tts -> default_tts`, `stt -> default_stt`. Summarization uses `default_summarization` -- catalog kind `chat` can map to it if the provider recommends a summarization model, but for now it auto-fills from the chat recommendation if `default_summarization` is empty.
- Only include kinds where the corresponding pref slot is currently `None`.
- `apply_defaults` writes suggestions into `prefs.llm` attributes and returns what was applied.

### 2b. Unit tests for suggestion logic

- Populates empty slots from first provider's recommendations.
- Skips already-set slots.
- Multi-provider: first provider's recommendation wins; second provider does not overwrite.
- Filters out unavailable models.
- Empty result when no providers have recommendations.

---

## Part 3: CLI Integration

### 3a. Wire into `interactive_credential_provisioning`

In [commands/provider.py](hiroserver/hirocli/src/hirocli/commands/provider.py), after the credential import/entry loop and **before** `print_provider_summary_table`:

1. Load current preferences via `load_preferences(workspace_path)`.
2. Build `AvailableModelsService` from catalog + credential store.
3. Call `compute_suggested_defaults(...)` with the IDs of all currently configured providers.
4. If suggestions exist, display them and prompt:
  - **Y (default):** Apply all and save preferences.
  - **n:** Skip entirely.
  - **pick:** Per-kind selection: for each suggestion, show the recommended model plus other available models of that kind, let user choose or skip.
5. Save preferences if changes were made.
6. Print summary of auto-set defaults (after the provider summary table).

### 3b. Wire into `provider add` command

After a successful `ProviderAddApiKeyTool().execute(...)` in the `provider_add` function, run the same default suggestion logic for the single newly added provider. Interactive prompt (same Y/n/pick).

### 3c. Wire into `provider scan-env --import-keys`

After `store.import_detected_env_keys()` succeeds and imports >0 keys, run the suggestion flow for all currently configured providers. Since `scan-env --import-keys` is a quick command, use the same interactive flow if TTY, or silent apply if non-interactive.

### 3d. Wire into `hirocli setup` non-interactive path

In `SetupTool.execute()` ([server.py](hiroserver/hirocli/src/hirocli/tools/server.py)), after `import_detected_env_keys()`, call `compute_suggested_defaults` and `apply_defaults` silently, then log at INFO what was set. No prompt needed (non-interactive).

### 3e. Add `hirocli provider suggest-defaults` command

New subcommand on the `provider` group:

- Loads preferences and credential store for the workspace.
- Calls `compute_suggested_defaults(...)` for all configured providers.
- Interactive prompt (same Y/n/pick) to apply.
- Can be run standalone at any time to fill empty preference slots.

### 3f. Tests for CLI integration

- Test the interactive prompt flow renders suggestions correctly (mock console).
- Test non-interactive path applies silently.
- Test `suggest-defaults` command with no empty slots prints "all defaults already set".

---

## Part 4: Admin UI follow-up (future, noted but NOT implemented in this phase)

The design doc marks this as "Phase 3a/3c follow-up":

- After adding a provider on the admin Providers page, show a notification/dialog offering to set recommended defaults.
- This is deferred -- it will be planned separately.

---

## Files Changed (summary)


| File                                                             | Change                                                                                                               |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `domain/model_catalog.py`                                        | Add `recommended_models` to `Provider`, validator, `suggested_defaults()`                                            |
| `catalog_data/catalog.yaml`                                      | Add `recommended_models` to all 6 providers                                                                          |
| `domain/preferences.py` (or new `domain/onboarding_defaults.py`) | `DefaultSuggestion`, `compute_suggested_defaults()`, `apply_defaults()`                                              |
| `commands/provider.py`                                           | Wire defaults into `interactive_credential_provisioning`, `provider_add`, `scan-env`, new `suggest-defaults` command |
| `tools/server.py`                                                | Silent auto-fill in non-interactive `SetupTool.execute()`                                                            |
| `domain/tests/test_model_catalog.py`                             | Validator and `suggested_defaults()` tests                                                                           |
| New test file for defaults logic                                 | `compute_suggested_defaults` / `apply_defaults` tests                                                                |
| `commands/tests/` or similar                                     | CLI integration tests                                                                                                |


---

## Mintdocs

Review and update documentation under `mintdocs/` if any existing pages reference the catalog or provider setup flow (per workspace rule). At minimum, update `first-time-setup.mdx` if the setup flow output changes.