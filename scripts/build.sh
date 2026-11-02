#!/usr/bin/env bash
# Build the flow-patched Yazi and install it as ~/.local/bin/yazi-flow-yazi.
#
#   scripts/build.sh            # clone (if needed), overlay modules/, build, install
#   scripts/build.sh --rebuild  # drop the checkout and clone the tag again
#
# The two preset components in modules/ are whole-file replacements for
# yazi-plugin/preset/components/{current,parent}.lua, which upstream embeds into the
# binary at compile time. Bumping YAZI_TAG means re-merging those two files by hand.
# The patched binary never replaces /usr/bin/yazi; the launcher picks it up by name.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/build/src"
TAG="${YAZI_TAG:-v26.9.1}"
DEST="${YAZI_FLOW_DEST:-$HOME/.local/bin}"
COMPONENTS=(current.lua parent.lua)

if [[ "${1:-}" == "--rebuild" ]]; then
	rm -rf "$SRC"
fi

if [[ ! -d "$SRC" ]]; then
	echo "==> cloning yazi $TAG"
	git clone --branch "$TAG" --depth 1 https://github.com/sxyazi/yazi "$SRC"
fi

cd "$SRC"
have="v$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' Cargo.toml | head -1)"
if [[ "$have" != "$TAG" ]]; then
	echo "!! $SRC has version $have, wanted $TAG (use --rebuild)" >&2
	exit 1
fi

echo "==> overlaying modules/ onto the checkout"
git checkout -- yazi-plugin/preset/components
for f in "${COMPONENTS[@]}"; do
	install -m 0644 "$ROOT/modules/$f" "yazi-plugin/preset/components/$f"
done

echo "==> cargo build --release (a few minutes on a cold target)"
cargo build --release --locked --bin yazi

mkdir -p "$DEST"
install -m 0755 "$SRC/target/release/yazi" "$DEST/yazi-flow-yazi"
ln -sfn "$ROOT/bin/yazi-flow" "$DEST/yazi-flow"
echo "==> installed $DEST/yazi-flow-yazi ($("$DEST/yazi-flow-yazi" --version | tr '\n' ' '))"
echo "==> linked   $DEST/yazi-flow -> $ROOT/bin/yazi-flow"
