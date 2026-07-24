#!/usr/bin/env bash
# Configure Cursor Cloud Agent git identity for this repo.
set -euo pipefail

git config --global user.name "lifeupriver"
git config --global user.email "blondes-coffee.9f@icloud.com"
git config --global commit.gpgsign false

HOOKS_DIR="${HOME}/.cursor/agent-hooks"
for hook_dir in "${HOOKS_DIR}"/*/commit-msg.cursor.co-author; do
  if [[ -f "${hook_dir}" ]]; then
    cat > "${hook_dir}" <<'EOF'
#!/bin/bash
# Co-author hook disabled: commits use lifeupriver as primary author.
exit 0
EOF
    chmod +x "${hook_dir}"
  fi
done

echo "Git identity set to lifeupriver <blondes-coffee.9f@icloud.com>"
