---
name: LLM Catalog Phase 2b
overview: "Phase 2b implements three workstreams: (1) interactive credential provisioning during first-time `hirocli setup`, (2) credential injection into TTS/STT providers and VisionService, and (3) character model validation warnings across tools, CLI, and admin UI."
todos:
  - id: setup-provisioning
    content: "Workstream A: Interactive credential provisioning in hirocli setup (--non-interactive flag, interactive_credential_provisioning() in commands/provider.py, wire into root.py setup command, TTY detection)"
    status: pending
  - id: tts-stt-injection
    content: "Workstream B1-B2: Add api_key constructor param to 4 TTS/STT providers, update both factory functions (create_tts_service, create_stt_service) to pull keys from credential store"
    status: pending
  - id: vision-rewrite
    content: "Workstream B3: Rewrite VisionService to accept workspace_path and use create_chat_model() from model factory instead of bare init_chat_model()"
    status: pending
  - id: media-tools-fix
    content: "Workstream B4: Fix TranscribeTool and DescribeImageTool in tools/media.py to use factory functions with workspace context instead of manual provider construction"
    status: pending
  - id: character-validation
    content: "Workstream C: Wire validate_character_models() into character tools (warnings in result), CLI commands (yellow console output), and admin controller (ui.notify warnings)"
    status: pending
  - id: tests
    content: Tests for interactive provisioning (mocked prompts), provider credential injection, vision service, media tools, and character validation warnings
    status: pending
  - id: design-doc-update
    content: "Update Phase 2b in llm_catalog_design.md: mark agent_manager bullet as already done, refine TTS/STT bullet wording to describe constructor injection pattern"
    status: pending
isProject: false
---

# LLM Catalog Phase 2b — Execution Plan

No backward compatibility (initial development mode).

---

## Key finding: agent_manager.py is already done

[agent_manager.py](hiroserver/hirocli/src/hirocli/runtime/agent_manager.py) already uses `create_chat_model()` from `model_factory.py` with `credential_store` injection (lines 83-128). The Phase 2b design doc bullet "Rewrite agent_manager.py" was completed during Phase 2a. No further changes needed.

---

## Workstream A — Interactive credential provisioning in `hirocli setup`

### Current state

- [server.py SetupTool](hiroserver/hirocli/src/hirocli/tools/server.py) (line 110) calls `CredentialStore.import_detected_env_keys()` which silently auto-imports ALL detected env keys with no user interaction
- [root.py setup command](hiroserver/hirocli/src/hirocli/commands/root.py) (line 144) prints a count of imported keys after the fact
- No interactive flow, no selective import, no manual entry loop

### Approach

Interactive prompting is a **CLI concern** (not suitable for the Tool layer which is also used by the AI agent). The interactive flow will be a function in `commands/provider.py` called from `commands/root.py` after `SetupTool` returns.

`SetupTool` keeps its current `import_detected_env_keys()` as the **non-interactive fallback** (for `--non-interactive`, non-TTY, and programmatic callers). The CLI command layer adds the interactive experience on top.

### Changes

**1. Add `--non-interactive` flag to setup command**

In [commands/root.py](hiroserver/hirocli/src/hirocli/commands/root.py), add a `non_interactive: bool` option to the `setup()` command. Pass it through to the tool via a new kwarg, and use it to decide which provisioning path runs.

**2. Split `SetupTool` to not auto-import when interactive mode is expected**

In [tools/server.py](hiroserver/hirocli/src/hirocli/tools/server.py), add a `skip_env_import: bool = False` parameter to `SetupTool.execute()`. When True, the tool skips `import_detected_env_keys()` — the CLI will handle it interactively. Add `skip_env_import` to `SetupResult`.

**3. Create `interactive_credential_provisioning()` in commands/provider.py**

New function in [commands/provider.py](hiroserver/hirocli/src/hirocli/commands/provider.py):

```python
def interactive_credential_provisioning(
    workspace_path: Path,
    workspace_id: str,
    console: Console,
) -> int:
```

Flow:

1. `Confirm.ask("Would you like to import API keys from your environment?")`
2. If yes: scan env using `get_model_catalog().list_providers()` + `os.environ.get()` for each `credential_env_keys`. Build a list of `(provider, env_var_name, masked_value)`. Present as a numbered checklist using Rich. User picks which to import (all / specific indices / none). Call `store.set_api_key()` for each selected.
3. After env import (or decline): loop — `Confirm.ask("Would you like to add an API key for another provider?")`. If yes, show unconfigured cloud providers as a numbered list. User picks one, `Prompt.ask("API key", password=True)`, store, repeat. If no, exit loop.
4. Print provider status summary using the existing `provider_list` table logic (extract the table-rendering from `provider_list` command into a helper `print_provider_summary_table()`).
5. Return count of providers configured.

**4. Wire into setup command**

In [commands/root.py](hiroserver/hirocli/src/hirocli/commands/root.py) `setup()`:

- After `SetupTool().execute(...)` returns, if interactive (TTY and not `--non-interactive`): call `interactive_credential_provisioning(workspace_path, workspace_id, console)`
- If non-interactive: the tool already ran `import_detected_env_keys()` as today

**5. TTY detection**

Use `sys.stdin.isatty()` to detect non-TTY. Skip interactive flow when False, even without `--non-interactive`.

---

## Workstream B — TTS/STT/Vision credential injection

### B1: Add `api_key` constructor param to TTS/STT providers

Four files, same pattern for each:

**[tts/openai_provider.py](hiroserver/hirocli/src/hirocli/services/tts/openai_provider.py):**

- Add `__init__(self, *, api_key: str | None = None)` storing `self._api_key`
- `is_available()`: check `self._api_key` instead of `os.environ.get("OPENAI_API_KEY")`; keep SDK import check
- `synthesize()` line 92: `AsyncOpenAI(api_key=self._api_key)` instead of `os.environ.get()`

**[tts/gemini_provider.py](hiroserver/hirocli/src/hirocli/services/tts/gemini_provider.py):**

- Add `__init__(self, *, api_key: str | None = None)` storing `self._api_key`
- `is_available()`: check `self._api_key` instead of `_api_key()` helper
- `synthesize()` line 120: `genai.Client(api_key=self._api_key)` instead of `_api_key()`
- Remove module-level `_api_key()` helper

**[stt/openai_provider.py](hiroserver/hirocli/src/hirocli/services/stt/openai_provider.py):**

- Same pattern as TTS OpenAI. `self._api_key` in constructor, remove `os.environ.get()` from `is_available()` and `transcribe()`

**[stt/gemini_provider.py](hiroserver/hirocli/src/hirocli/services/stt/gemini_provider.py):**

- Same pattern as TTS Gemini. `self._api_key` in constructor, remove `_api_key()` helper

### B2: Update factory functions to inject credentials from store

**[tts/init.py](hiroserver/hirocli/src/hirocli/services/tts/__init__.py) `create_tts_service()`:**

- Add credential store resolution (same pattern as `create_stt_service` already uses): `workspace_id_for_path`, `CredentialStore`, `get_api_key(provider_id)`
- Map voice provider to catalog provider_id (the `_PROVIDER_MAP` keys already match)
- Construct provider with API key: `cls(api_key=api_key)` instead of `cls()`

**[stt/init.py](hiroserver/hirocli/src/hirocli/services/stt/__init__.py) `create_stt_service()`:**

- Already has credential store. Just pass API key to provider constructor: `cls(api_key=store.get_api_key(spec.provider_id))` instead of `cls()`
- Remove the comment about "API keys still from env"

### B3: Rewrite VisionService to use model factory

**[vision_service.py](hiroserver/hirocli/src/hirocli/services/vision_service.py):**

- Add `workspace_path: Path | None = None` to `__init`__
- `is_available()`: if workspace_path is set, use credential store to check if the vision model's provider is configured. Fall back to env check when no workspace_path (backward compat for tool usage).
- `_get_model()`: use `create_chat_model()` from `model_factory` instead of bare `init_chat_model()`. Resolve model from preferences or env var, pass through model factory with credential injection.

**Update callers:**

- [message_adapter.py](hiroserver/hirocli/src/hirocli/runtime/message_adapter.py) line 111: `VisionService(workspace_path=workspace_path)` instead of `VisionService()`

### B4: Fix TranscribeTool and DescribeImageTool to use factories

**[tools/media.py TranscribeTool](hiroserver/hirocli/src/hirocli/tools/media.py) (lines 56-70):**

- Replace manual `STTService(providers=[OpenAISTTProvider(), GeminiSTTProvider()])` with `create_stt_service(workspace_path)` using workspace from tool context (add `workspace` param to the tool)

**[tools/media.py DescribeImageTool](hiroserver/hirocli/src/hirocli/tools/media.py) (lines 99-113):**

- Replace `VisionService()` with `VisionService(workspace_path=workspace_path)` using workspace from tool context (add `workspace` param)

---

## Workstream C — Character model validation warnings

### Approach

`AvailableModelsService.validate_character_models()` already exists and returns `CharacterModelValidation` with buckets: `unknown_llm`, `deprecated_llm`, `wrong_kind_llm`, `unavailable_llm` (and voice equivalents). The task is to call it at the right points and surface warnings without blocking saves.

### Changes

**1. Add a shared validation helper**

Add a function in [tools/character.py](hiroserver/hirocli/src/hirocli/tools/character.py) (or a new small helper module) that takes workspace_path + llm_models + voice_models, runs `validate_character_models()`, and returns a list of warning strings:

```python
def _validate_model_warnings(
    workspace_path: Path, llm_models: list[str] | None, voice_models: list[str] | None,
) -> list[str]:
```

**2. Wire into CharacterCreateTool / CharacterUpdateTool**

In [tools/character.py](hiroserver/hirocli/src/hirocli/tools/character.py): after `create_character` / `update_character` succeeds, call `_validate_model_warnings()`. Add a `warnings: list[str]` field to `CharacterCreateResult` and `CharacterUpdateResult`. The tool returns warnings alongside the character data — callers decide how to display them.

**3. Wire into CLI commands**

In [commands/character.py](hiroserver/hirocli/src/hirocli/commands/character.py): after successful create/update, check `result.warnings` and print each as `console.print(f"[yellow]Warning: {w}[/yellow]")`.

**4. Wire into admin UI**

In [admin/features/characters/controller.py](hiroserver/hirocli/src/hirocli/admin/features/characters/controller.py) `_save_character()`: after the `run.io_bound(...)` save call succeeds, check `res.warnings` (from the service result). For each warning, call `ui.notify(w, color="warning")`. This requires the admin `CharacterService.create_character/update_character` to return warnings from the tool.

---

## Testing

- **Workstream A**: Test `interactive_credential_provisioning` with mocked `Confirm.ask`/`Prompt.ask`, mocked env vars, and `_test_secrets` credential store. Test non-interactive path (existing `import_detected_env_keys` behavior).
- **Workstream B**: Test each provider with injected `api_key` (no env var set, key passed via constructor). Test factory functions with mock credential store. Test `TranscribeTool`/`DescribeImageTool` with workspace param.
- **Workstream C**: Test `_validate_model_warnings` returns correct warnings for unknown/deprecated/wrong-kind/unavailable models.

