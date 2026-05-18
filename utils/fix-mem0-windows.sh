# Run from the Mem0 repo root, before building containers.
# chmod +x fix-mem0-windows.sh
# ./fix-mem0-windows.sh
# cd server
# docker compose up -d --build --force-recreate


#!/usr/bin/env bash
set -euo pipefail

echo "🔧 Fixing Mem0 repo for Docker on Windows/Git Bash..."

# 1) Force Linux line endings for Docker-related files
echo "📝 Adding .gitattributes rules..."
cat > .gitattributes <<'EOF'
*.sh text eol=lf
*.env text eol=lf
Dockerfile text eol=lf
*.yml text eol=lf
*.yaml text eol=lf
EOF

# 2) Convert shell scripts to LF and make executable
echo "🔁 Converting .sh files to LF and making them executable..."
find . -type f -name "*.sh" -print0 | while IFS= read -r -d '' file; do
  sed -i 's/\r$//' "$file"
  chmod +x "$file"
  echo "  ✅ $file"
done

# 3) Convert Docker/env/yaml files to LF
echo "🔁 Converting Docker/env config files to LF..."
find . -type f \( \
  -name ".env" -o \
  -name "*.env" -o \
  -name "*.yml" -o \
  -name "*.yaml" -o \
  -name "Dockerfile" \
\) -print0 | while IFS= read -r -d '' file; do
  sed -i 's/\r$//' "$file"
  echo "  ✅ $file"
done

# 4) Patch Dockerfiles from Node 20 to Node 22
echo "🟢 Updating Dockerfiles from Node 20 to Node 22..."
find . -type f -name "Dockerfile" -print0 | while IFS= read -r -d '' file; do
  sed -i \
    -e 's/FROM node:20-alpine/FROM node:22-alpine/g' \
    -e 's/FROM node:20-slim/FROM node:22-slim/g' \
    -e 's/FROM node:20/FROM node:22/g' \
    "$file"

  if grep -q "FROM node:22" "$file"; then
    echo "  ✅ $file"
  fi
done

# 5) Ask Git to respect LF for future checkouts in this repo
echo "⚙️ Setting local Git line-ending behavior..."
git config core.autocrlf false
git config core.eol lf

echo ""
echo "✅ Done."
echo ""
echo "Next:"
echo "  cd server"
echo "  docker compose down -v   # only if old broken volumes exist"
echo "  docker compose up -d --build --force-recreate"