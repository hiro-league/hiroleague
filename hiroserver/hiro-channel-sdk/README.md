# Hiro Channel SDK

The wire between the HiroLeague core and every extension: its apps and its channel plugins.

## Overview

Every extension signs in on the core's one extension socket (live: `ws://127.0.0.1:18082`) with its own key, then
exchanges UnifiedMessage frames with the core: requests, responses and events.

- An app uses `ExtensionClient` (through the backend kit, `hiro-extension-kit`).
- A channel plugin (WhatsApp, devices, echo...) is a standalone Python package that implements `ChannelPlugin`; the
  core starts it, and `PluginRunner` runs it on an `ExtensionClient`: it pairs with the code the core puts in its
  environment (`HIRO_PAIRING_CODE`), keeps its key in the folder it is given (`--key-dir`), starts on the settings
  the core sends (`extension.configure`), answers its own methods (`on_call`), and relays other people's messages
  both ways (`emit`, `send`).

## Writing a channel plugin

Implement `ChannelPlugin` (`base.py`), then in its entry point:

```python
log_setup.run(PluginRunner(MyChannel(), hiro_ws, Path(key_dir)).run())
```

`hiro-channel-echo` is the smallest example.
