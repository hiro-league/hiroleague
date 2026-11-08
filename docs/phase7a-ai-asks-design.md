# Phase 7a: the core answers questions (build contract)

Plan: the Claude Doc "HiroLeague and Home: the plan in steps", Phase 7a. Mock-ups (agreed): admin
`/catalog/?tab=profiles|uses|providers` (`admin_frontend/src/lib/features/catalog/ai/`), HomeHiro
`/settings?tab=fromhiro` (`frontend/src/lib/features/settings/ai-from-hiroleague/`). This file is the contract
every part builds to. No backward compatibility (dev/revamp mode); family data is never lost.

## 1. AI profile (core, preferences)

Stored like `image_profiles` (preferences.json, its own page edits it through the preferences API):
`ai.profiles: dict[profile_id, AiProfile]`, `ai.uses: dict[use_key, profile_id | None]` where
`use_key = "<extension name>:<use id>"` (e.g. `home:ask`).

| Field | Type | Notes |
|---|---|---|
| label | str (1–80) | "Camera questions" |
| model | catalog id `provider:model` | API providers from the catalog; `lm_studio:*`, `ollama:*` (local, model as the server reports it); `claude_code:*`, `codex:*` (plan, model as the tool reports it) |
| thinking | ThinkingLevel or None | levels the model supports (catalog `reasoning_efforts` / `thinking_off_type`) |
| temperature | float 0–2 or None | None = model default; ignored where the provider ignores it |
| max_tokens | int or None | None = model default |
| num_ctx | int or None | local models only |
| instructions | str (optional, may be empty) | appended to every question |
| max_cost_day | float USD or None | API models; "day" = the home's local day |
| max_per_hour | int or None | plan and local models |
| at_once | int 1–4 (default 1) | parallel asks on this profile |
| fallback | profile_id or None | chain ≤ 3 after the profile itself, no loops (validated on write) |

Reuse `model_factory` / `ModelTuning` for the API path (it already handles each provider's thinking/temperature
quirks). Do NOT add a second tuning concept; 7b folds tuning profiles into AI profiles later.

## 2. Uses (declared by the extension)

`ExtensionInfo` (SDK) gains `uses: list[ExtensionUse]`:
`ExtensionUse{id, name, pictures: int (0 = none, else max), sound: bool, json: bool}`. HomeHiro declares
`ask` (Ask a camera; pictures = the most HomeHiro sends today, read it from its code), `wakeword` (sound, json), `sites` (json), `write`
(json), `study` (pictures 60, json). The core stores the last list per extension (extensions table `info`).
`extension.info` returns it too, so the Uses page's Refresh asks again (`ExtensionManager.request(id,
"extension.info")`). The Uses page marks uses new (not in the previous list) and removed (in `ai.uses` but no
longer declared: greyed, Forget deletes the key).

## 3. The ask (extension request, extensions only)

Request `ai.ask` (CALLER_EXTENSION only). Params:
`{use, profile?: id, prompt, pictures?: [base64 JPEG], picture_labels?: [str], sound?: {b64, mime},
schema: JSONSchema, detail?: "low"|"medium"|"high", local_only?: bool, timeout?: seconds, wait?: bool}`
- profile given → that profile (a copy's own pick); else `ai.uses[ext:use]`; neither → error `no_profile`.
- `wait` false = an app's line (StudyHiro): a busy plan tool answers `busy` instead of queueing.
- `local_only` skips non-local profiles in the chain.
Answer (ok): `{text (JSON text), profile_id, profile_name, provider, model, plan: bool, ms, tokens, tokens_in,
tokens_out, cost (USD|None), estimate (USD|None, plan), notes: [str] (profiles passed over and why), tries:
[{profile_id, provider, model, status: ok|failed|skipped, error?, ms}]}`. Errors: `no_profile`, `budget`
(every profile in the chain over budget), `busy`, `failed` (all tried failed; message says why), `invalid`.
This mirrors HomeHiro's `Asked` so its log keeps recording from the answer.

Request `ai.profiles` (extensions only): the profiles (id, label, model + provider label, kind api|local|plan,
budget hint, today's use, fallback chain) and this extension's use → profile map. HomeHiro's pickers use it.

Extension socket message size: raise `max_size` on both ends (core `websockets.serve`, SDK
`websockets.connect`) to 64 MiB (60 pictures as base64). The SDK's `request()` takes a timeout (study: 900 s).

## 4. Running an ask (core service `services/ai_ask/`)

- Fallback walk: profile → fallback … (≤ 3). Move on when: over budget, provider failed/timeout, `local_only`
  rules it out, a plan tool is busy and `wait` is false is NOT a move-on (answer `busy`).
- Budget counting: `ai_usage` table in workspace.db (profile_id, hour start, asks, cost) — enough for
  max_cost_day / max_per_hour; at_once = an in-process semaphore per profile.
- API and local: LangChain chat model from `model_factory` with tuning from the profile; pictures as image
  content parts; sound as an audio part (Gemini); `with_structured_output(schema)` or JSON mode, returning
  JSON text. Token counts from usage metadata (`hiro_commons.llm_usage`), cost from the catalog pricing.
- Local servers: Ollama / LM Studio keep one address per kind (established). LM Studio is un-hidden in the
  catalog. Models a local server reports are offered as `lm_studio:<name>` / `ollama:<name>` even without a
  catalog row (a "discovered models" read, not catalog edits). Loading and unloading idle models as HomeHiro's
  `llm/local.py` does (port that logic), one ask at a time per server.
- Plan tools (`claude_code`, `codex`, catalog hosting `plan`, `tool_calling: false`): port HomeHiro's
  `agents/` (cli.py run with a clean env and a temp folder per ask; Claude `-p --output-format json
  --json-schema`, Codex `exec --output-schema … -i pic`; strict-schema helper for Codex; sign-in flows; nightly
  npm updates; a queue ("line") per tool). Logins and tools live under the workspace
  (`<workspace>/plans/<tool>/`, tools in `<workspace>/plans/tools`). Models from the tool itself.
- Everything callable from the admin/CLI/agent is a Tool (tools architecture): profile CRUD goes through
  preferences; plus `ai_profiles_list`, `ai_try` (Try it), `ai_uses_list/set/forget/refresh`,
  `plan_status/sign_in/sign_out/update/test`, `local_server_check`, `ai_import_homehiro`.

## 5. Admin (wire the mock-ups)

Replace `ai-mock-data.ts` reads with the API; keep the agreed UI: profiles tab (SingleModelPicker, temperature
slider, optional extra instructions, budget, fallback, Try it), uses tab (per extension, Refresh, new/removed),
providers tab rows for local servers and plan tools in the existing columns with tooltip + Manage/Server
dialogs. Remove the mock banner and mock-only badges. Fix the picker wording where it reads as Preferences
("No workspace default set.") only if it can be done without changing other callers.

## 6. HomeHiro

- `llm/profiles.ask(...)` keeps its signature; its body asks the core (`hiroleague.link.client.request("ai.ask",
  ..., timeout)`) and maps the answer to `Asked`; `recorder` keeps logging (7a keeps HomeHiro's log pages).
- Core not connected / error → raise the same errors callers handle today (`LimitReached` for budget, a
  failure otherwise); Busy for an app's line.
- Pickers (ask-model, wake-panel, sites-suggested, the Write text node) list the core's profiles
  (`ai.profiles`, cached; last list kept when the core is down). Write text becomes the `write` use.
- apps API (`/api/apps/ask`) keeps its address, key and shape and relays to the core as use `study`, `wait` false.
- HomeHiro declares its five uses in `INFO` (hiroleague.py).
- Removed: `llm/` except the recorder/usage/requests (log pages, 7b), `llm_api.py`, `llm/servers_api.py`,
  `agents/`, the settings pages LLM profiles / Providers / AI agents / Playground, the mock tab becomes the real
  "AI from HiroLeague" tab. Tables `LlmProfile`, `LlmDefault`, `LlmServer` dropped only after the import.

## 7. Import (once, on a copy first)

`hiro ai import-homehiro <path to homehiro.db>` (Tool): reads LlmProfile, LlmDefault, LlmServer; writes AI
profiles (ids kept as `hh-<id>` or slugified names; fallback links mapped), `ai.uses` for `home:<use>`, and the
local server addresses (Ollama / LM Studio). Plan tools are signed in again in the core. Dry-run prints what it
would write.
