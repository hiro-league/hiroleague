#!/usr/bin/env bash

GIT_BASH='C:\Program Files\Git\bin\bash.exe'

wt.exe \
  new-tab --title "Mint Docs" -p "Git Bash" "$GIT_BASH" --login -lc "cd /d/projects/hiro-docs/mintdocs && mint dev" \
  \; new-tab --title "Admin Frontend" -p "Git Bash" "$GIT_BASH" --login -lc "cd /d/projects/hiroleague && npm --prefix admin_frontend install && npm --prefix admin_frontend run dev"
