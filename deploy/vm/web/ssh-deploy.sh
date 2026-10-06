#!/usr/bin/env bash
# Root-owned forced SSH command for the GitHub Actions deployment key.
set -euo pipefail
if [[ ${SSH_ORIGINAL_COMMAND:-} =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
    exec /usr/local/lib/aivideo/deploy-release.sh "${BASH_REMATCH[1]}"
fi
echo 'Only deploy COMMIT_SHA is permitted for this key.' >&2
exit 1
