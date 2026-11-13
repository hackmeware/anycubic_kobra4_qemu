#!/usr/bin/env bash
# Optional workspace-local Linux x86_64 runtime. Does not use sudo.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUNTIME=${RENODE_RUNTIME:-"$ROOT/../at32-runtime"}
VERSION=1.17.0
URL="https://github.com/renode/renode/releases/download/v$VERSION/renode-$VERSION.linux-portable.tar.gz"
mkdir -p "$RUNTIME/home/.config"
if [[ ! -x "$RUNTIME/renode_${VERSION}-portable/renode" ]]; then
    curl -fL "$URL" -o "$RUNTIME/renode.tar.gz"
    tar -xzf "$RUNTIME/renode.tar.gz" -C "$RUNTIME"
fi
python3 -m venv "$RUNTIME/venv"
HOME="$RUNTIME/home" "$RUNTIME/venv/bin/pip" install -r "$RUNTIME/renode_${VERSION}-portable/tests/requirements.txt"
HOME="$RUNTIME/home" XDG_CONFIG_HOME="$RUNTIME/home/.config" "$RUNTIME/renode_${VERSION}-portable/renode" --version
cat > "$RUNTIME/run-renode" <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
export HOME="${RENODE_HOME:-$HERE/home}"
export XDG_CONFIG_HOME="$HOME/.config"
export TMPDIR=$(mktemp -d "${TMPDIR:-/tmp}/at32-renode.XXXXXX")
mkdir -p "$XDG_CONFIG_HOME"
exec "$HERE/renode_1.17.0-portable/renode" "$@"
WRAPPER
chmod +x "$RUNTIME/run-renode"
