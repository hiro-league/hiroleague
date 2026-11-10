Commit, push and deploy are one job, done in this order and never left half-done. GitHub (`origin`) is never
behind what runs on Simone.

- **"Commit"** = run the repo's check (`./scripts/check.sh`), commit, then push to GitHub (`origin`).
- **"Deploy"** (or "commit and deploy", "release") = check → commit → push to GitHub → deploy to Simone (`server`)
  → verify there. Never deploy something GitHub doesn't have yet.
- **Which branches:**
  - **HiroLeague:** work on the working branch (e.g. `phase7b`), move `dev` to it, push `dev` (and the working branch) to `origin`, then `git push server dev:main`.
  - **HomeHiro:** move `main` to the working branch, push it to `origin`, then `git push server main`.
  - **hiro-docs:** push `dev` to `origin` (no Simone deploy).
- **Pushes are fast-forward only.** If GitHub has commits we don't, stop and tell Michel. Never force-push.
- **When something stops the job** (a failing check, a refused push, a failed deploy), say what is done and what isn't.
- **When offering next steps**, offer the whole job ("Commit and deploy" = all of the above), not a piece of it.
