---
paths:
  - "hiroserver/**/*.py"
---

# Human-first logging

For **operational / message-flow** logs: the **first argument** (message string) must carry **what happened**, **who** (human-readable label when known), and **what kind** (short summary). Optional emoji: `✅` `❌` `⚠️` `🔌` `⬇️` `⬆️`. Typical shape: `{emoji} {action} — {peer} · {kind}`.

**When to log (INFO):** message-flow milestones (received / acked / dispatched / agent-in / agent-out / sent), state transitions (connect / disconnect / pair / auth), and outcomes of external calls (STT/TTS/LLM/persistence) with `elapsed_ms`. Skip per-token / per-chunk noise and re-logging of the same hop — log once at the layer that owns the transition. Use `DEBUG` for payload dumps, `WARNING`/`ERROR` for anomalies (with `exc_info=True` when useful).

**Structured extras** (keyword args / `fields`): put **readable** fields first — e.g. `content_hint`, `error`, `elapsed_ms`, short status text — then **opaque** fields last (`msg_id`, `device_id`, `sender_id`, `target_id`). Use `exc_info=True` on errors when useful.

**Direction (server-centric):** `⬇️` **inbound** = traffic that **ends up at the server** (hirocli / HiroServer). `⬆️` **outbound** = traffic that **leaves the server** toward clients, devices, channels, or upstream services — whatever the hop, the arrow matches the path **relative to the server**.

**Kind helpers:** Reuse shared helpers where they exist (e.g. `_comm_kind` / `_comm_content_hint` / `_comm_extras` in hirocli; `_relay_kind` / `_relay_content_hint` on the gateway). **Kind** belongs in the message string; rich detail belongs in extras, ordered as above.

**Label the server** as **HiroServer** in gateway logs when referring to the desktop/hirocli side.
