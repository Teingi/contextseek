#!/usr/bin/env bash
# Bundle the Python sidecar into a single self-contained executable so the
# desktop app needs no pre-installed Python. The output is placed where Tauri's
# `externalBin` expects it: desktop/tauri/src-tauri/binaries/
#   contextseek-desktop-server-<target-triple>[.exe]
#
# Requires: a Python with `contextseek[http,seekdb,openai]` + pyinstaller.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
OUT_DIR="${REPO_ROOT}/desktop/tauri/src-tauri/binaries"
NAME="contextseek-desktop-server"

# Resolve Rust target triple so the filename matches Tauri's sidecar convention.
TRIPLE="${TAURI_TARGET_TRIPLE:-$(rustc -Vv 2>/dev/null | sed -n 's/^host: //p')}"
if [ -z "${TRIPLE}" ]; then
  echo "error: cannot determine target triple (set TAURI_TARGET_TRIPLE or install rustc)" >&2
  exit 1
fi

EXE=""
case "${TRIPLE}" in
  *windows*) EXE=".exe" ;;
esac

mkdir -p "${OUT_DIR}"

# Entry shim: invoke the CLI's desktop-server subcommand.
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
cat > "${WORK}/entry.py" <<'PYEOF'
import sys
from contextseek.cli.main import main

if __name__ == "__main__":
    # Forward all args to: contextseek desktop-server ...
    sys.argv = ["contextseek", "desktop-server", *sys.argv[1:]]
    raise SystemExit(main())
PYEOF

"${PY}" -m PyInstaller \
  --noconfirm --clean --onefile \
  --name "${NAME}" \
  --distpath "${WORK}/dist" \
  --workpath "${WORK}/build" \
  --specpath "${WORK}" \
  --collect-all contextseek \
  --collect-all pyseekdb \
  --collect-all pylibseekdb \
  --copy-metadata pylibseekdb \
  --hidden-import libseekdb_python \
  --collect-submodules langchain_openai \
  "${WORK}/entry.py"

cp "${WORK}/dist/${NAME}${EXE}" "${OUT_DIR}/${NAME}-${TRIPLE}${EXE}"
echo "sidecar -> ${OUT_DIR}/${NAME}-${TRIPLE}${EXE}"
