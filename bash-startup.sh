#!/usr/bin/env bash

GIT_BASH='C:\Program Files\Git\bin\bash.exe'

wt.exe \
  new-tab --title "Mint Docs" -p "Git Bash" "$GIT_BASH" --login -lc "cd /d/projects/hiro-docs/mintdocs && mint dev" \
  \; new-tab --title "Flutter Web" -p "Git Bash" "$GIT_BASH" --login -lc "cd /d/projects/hiroleague/device_apps && HIRO_ENV=dev ./flutter_build.sh run --dart-define=HIRO_ENV=dev -d chrome --web-port 63000" \
  \; new-tab --title "Admin Frontend" -p "Git Bash" "$GIT_BASH" --login -lc "cd /d/projects/hiroleague && npm --prefix admin_frontend install && npm --prefix admin_frontend run dev"