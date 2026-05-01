# Hiro Gateway

**Hiro Gateway** — WebSocket relay server.

Accepts connections from Hiro desktop servers and online apps, performs
challenge/response authentication, and relays messages between authenticated
devices identified by `device_id`.

## Quick Start

TBD

## How it works

1. Every new socket receives an auth challenge nonce.
2. A desktop client authenticates using its master key (`auth_mode=desktop`) against
   the desktop trust root configured at startup (`--desktop-pubkey`).
3. A device client authenticates with desktop attestation + nonce signature
   (`auth_mode=device`).
4. Once authenticated, messages are relayed by `device_id`.

## Message Format

TBD