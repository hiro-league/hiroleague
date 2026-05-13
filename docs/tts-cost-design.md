# TTS Cost Accumulation Design

## Request

Add estimated cost for TTS calls and accumulate it into the existing per-run agent cost that is already calculated for regular LLM calls.

The TTS cost calculation must depend on the TTS provider and model. The pricing rules come from `docs/model_pricing.md` and should be treated as the source of truth for this change.

If a TTS provider or model is not supported by the pricing rules, log a warning and skip TTS cost for that call. Do not add a fallback estimate for unknown providers.

## Existing Boundary

The current LLM cost path is:

1. The agent graph emits `graph.llm.usage`.
2. `GraphEventSubscriber` accumulates the estimated LLM cost in per-run state.
3. On `graph.run.completed`, the subscriber writes `metadata.agent.cost`.

TTS should follow the same accumulation model. It should add to the same run-level cost total instead of creating a separate persisted cost field.

## Proposed Design

Keep pricing logic in the catalog/domain layer by adding a TTS-specific estimator near the existing token cost estimator in `hirocli.domain.model_catalog`.

Keep accumulation in `GraphEventSubscriber`, because it already owns the run-level cost state and final `metadata.agent.cost` write.

Use the existing `graph.tts.completed` event. Extend its payload with the metering fields needed to price the TTS call:

- `provider`
- `model`
- `input_characters`
- `input_text_tokens`
- `generated_audio_seconds`
- `output_audio_tokens`
- optional provider usage metadata when available

Extend `TTSResult` so providers can return `provider` and optional usage metadata alongside the existing audio output fields.

## Pricing Rules

OpenAI:

- `tts-1` and `tts-1-hd`: calculate from input character count.
- `gpt-4o-mini-tts`: calculate from input text tokens plus generated audio seconds.
- If exact input token usage is not returned by the provider, estimate input text tokens locally.

Gemini:

- Calculate from text input tokens and audio output tokens from `usageMetadata`.
- If required usage metadata is unavailable, log a warning and skip TTS cost for that call.

Other providers:

- Log a warning and skip TTS cost for that call.

## Final Metadata Behavior

TTS cost should accumulate over the existing LLM cost:

```json
{
  "agent": {
    "cost": {
      "currency": "USD",
      "estimated_total": 0.000123,
      "pricing_available": true
    }
  }
}
```

Unsupported TTS pricing should not make the whole run's `pricing_available` false. It should only omit that TTS call from the total, because the regular LLM cost may still be valid.

## Implementation Touch Points

- `hiroserver/hirocli/src/hirocli/domain/model_catalog.py`
- `hiroserver/hirocli/src/hirocli/services/tts/provider.py`
- `hiroserver/hirocli/src/hirocli/services/tts/openai_provider.py`
- `hiroserver/hirocli/src/hirocli/services/tts/gemini_provider.py`
- `hiroserver/hirocli/src/hirocli/runtime/agent_graph/base.py`
- `hiroserver/hirocli/src/hirocli/runtime/graph_event_subscriber.py`
- catalog and graph subscriber tests
