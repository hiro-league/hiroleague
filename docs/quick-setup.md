## First-time workspace + gateway

**Naming a workspace:** Create it **before** `hirocli setup --workspace <name>`. Plain `hirocli setup` (no `--workspace`) is enough when you want the auto-created **`default`** workspace instead.

1. **Workspace:**  
   `hirocli workspace create home --set-default`  
   (pick any name instead of `home`)

2. **Desktop setup:**  
   `hirocli setup --workspace home`  
   Enter the gateway URL you will use (e.g. `ws://localhost:8765` if the gateway runs on this PC). Copy **`desktop_pub`** from the printed summary.

3. **Gateway:** Create an instance with that same **`desktop_pub`** and a port that matches your URL (example port **8765**):  
   `hirogateway instance create home --port 8765 --desktop-pubkey "<paste-desktop_pub>" --set-default`  
   From the repo dev tree use `uv run hirogateway …` under `hiroserver` if `hirogateway` is not on your PATH.

4. **Run:** Start the gateway (`hirogateway start` or `hirogateway`), then start the desktop server (`hirocli start`).

---

## Removing Hiro from startup

### Supported (CLI)

1. **Desktop server:** run `hirocli teardown`. Use `--purge` if you also want the workspace folder removed. Optional: `--workspace <name-or-id>` if you have several workspaces.
2. **Gateway:** run `hirogateway teardown`. Use `--instance <name>` if you are not using the default instance. If teardown fails because of how the startup task was created, retry with `--elevated-task`.

### Manual (only if teardown did not clean up)

1. Open **Task Scheduler** and delete any tasks whose names start with `hirocli-` or `hirogateway-`.
2. Open **Registry Editor**, go to your account’s startup Run location (**Current User → Software → Microsoft → Windows → CurrentVersion → Run**), and delete any values whose names start with `hirocli` or `hirogateway`.
