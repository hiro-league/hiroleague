## OpenAI STT cost table

| Models | Inputs + exact path | Formula|
| ------- | ------------------ | ------- |
| `whisper-1`  | `seconds = usage.seconds`<br>`price_per_minute` | `cost = (seconds / 60) × price_per_minute`|
| `gpt-4o-transcribe`<br>`gpt-4o-mini-transcribe`<br>`gpt-4o-transcribe-diarize` | `audio_tokens = usage.input_token_details.audio_tokens`<br>`output_tokens = usage.output_tokens`<br>`audio_input_price_per_1M`<br>`output_price_per_1M` | `cost = ((audio_tokens × audio_input_price_per_1M) + (output_tokens × output_price_per_1M)) / 1_000_000` |


## OpenAI STT model pricing

| Model                       | `price_per_minute` |`audio_input_price_per_1M` |`output_price_per_1M` |
| --------------------------- | -----------------: | --------------------------: | ---------------------: |
| `whisper-1`                 |           `$0.006` |                           — |                        — |
| `gpt-4o-mini-transcribe`    |                  — |                           `$1.25` |                      `$5.00` |
| `gpt-4o-transcribe`         |                  — |                           `$2.50` |                     `$10.00` |


## Gemini STT cost table — Gemini 3 / 3.1


| Models | Inputs + exact path | Formula|
| ------- | ------------------ | ------- |
| `gemini-3.1-flash-lite`<br>`gemini-3.1-flash-lite-preview`<br>`gemini-3-flash-preview`<br>`gemini-3.1-pro-preview` | `audio_tokens = usageMetadata.promptTokensDetails[].tokenCount` where `modality = "AUDIO"`<br>`output_tokens = usageMetadata.candidatesTokenCount`<br>`audio_input_price_per_1M`<br>`output_price_per_1M` | `cost = ((audio_tokens × audio_input_price_per_1M) + (output_tokens × output_price_per_1M)) / 1_000_000` |


## Current price values to plug in — Standard tier

| Model                           |`audio_input_price_per_1M` | `output_price_per_1M` |
| ------------------------------- | --------------------------: | ---------------------: |
| `gemini-3.1-flash-lite`         |                           `$0.50` |                     `$1.50` |
| `gemini-3.1-flash-lite-preview` |                           `$0.50` |                     `$1.50` |
| `gemini-3-flash-preview`        |                           `$1.00` |                     `$3.00` |
| `gemini-3.1-pro-preview`        | not separately listed for audio; use standard input price by context size |               `$12.00` if prompt ≤ 200k tokens; `$18.00` if prompt > 200k tokens |



## OpenAI TTS cost table


| Models                | Inputs needed | Formula |
| --------------------- | ------------- | ------- |
| `tts-1`<br>`tts-1-hd` | `input_characters = input.length`<br>`price_per_1M_characters`                                               | `cost = input_characters × price_per_1M_characters / 1_000_000`                                                                     |
| `gpt-4o-mini-tts`     | `input_text_tokens`<br>`generated_audio_seconds`<br>`text_input_price_per_1M`<br>`audio_output_price_per_1M` | `cost = (input_text_tokens × text_input_price_per_1M / 1_000_000) + (generated_audio_seconds × audio_output_price_per_1M / 48_000)` |



## Gemini TTS Cost Table

| Models                                           | Inputs + exact path                                                                                                                                                                                                                                         | Formula                                                                                                                  |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `gemini-3.1-flash-tts-preview`     or any other model              | `input_text_tokens = usageMetadata.promptTokensDetails[].tokenCount where modality="TEXT"`<br>`output_audio_tokens = usageMetadata.candidatesTokensDetails[].tokenCount where modality="AUDIO"`<br>`text_input_price_per_1M`<br>`audio_output_price_per_1M` | `cost = ((input_text_tokens × text_input_price_per_1M) + (output_audio_tokens × audio_output_price_per_1M)) / 1_000_000` |
