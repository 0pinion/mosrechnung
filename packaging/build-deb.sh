#!/bin/sh
set -eu

PACKAGE_VERSION="${1:-0.1.3}"
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STAGING_DIR=$(mktemp -d)
PACKAGE_ROOT="$STAGING_DIR/mosrechnung"

cleanup() {
    rm -rf -- "$STAGING_DIR"
}
trap cleanup EXIT INT TERM

mkdir -p \
    "$PACKAGE_ROOT/DEBIAN" \
    "$PACKAGE_ROOT/usr/bin" \
    "$PACKAGE_ROOT/usr/lib/mosrechnung" \
    "$PACKAGE_ROOT/usr/share/applications" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps" \
    "$PROJECT_ROOT/dist"

cp -R "$PROJECT_ROOT/src/mosrechnung" "$PACKAGE_ROOT/usr/lib/mosrechnung/"
cp "$PROJECT_ROOT/logoicon1.png" "$PACKAGE_ROOT/usr/lib/mosrechnung/logoicon1.png"
find "$PACKAGE_ROOT/usr/lib/mosrechnung" -type d -name __pycache__ -exec rm -rf -- {} +

sed "s/@VERSION@/$PACKAGE_VERSION/g" \
    "$PROJECT_ROOT/packaging/debian/control" > "$PACKAGE_ROOT/DEBIAN/control"
cp "$PROJECT_ROOT/packaging/mosrechnung" "$PACKAGE_ROOT/usr/bin/mosrechnung"
cp "$PROJECT_ROOT/packaging/mosrechnung.desktop" "$PACKAGE_ROOT/usr/share/applications/mosrechnung.desktop"
cp "$PROJECT_ROOT/packaging/mosrechnung.svg" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/mosrechnung.svg"
chmod 0755 "$PACKAGE_ROOT/usr/bin/mosrechnung"

PACKAGE_OUTPUT="$PROJECT_ROOT/dist/mosrechnung_${PACKAGE_VERSION}_all.deb"

if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --root-owner-group --build "$PACKAGE_ROOT" "$PACKAGE_OUTPUT"
else
    ARCHIVE_DIR="$STAGING_DIR/archive"
    mkdir -p "$ARCHIVE_DIR"
    printf '2.0\n' > "$ARCHIVE_DIR/debian-binary"
    tar --owner=0 --group=0 -C "$PACKAGE_ROOT/DEBIAN" -cJf "$ARCHIVE_DIR/control.tar.xz" .
    tar --owner=0 --group=0 --exclude='./DEBIAN' -C "$PACKAGE_ROOT" -cJf "$ARCHIVE_DIR/data.tar.xz" .
    rm -f -- "$PACKAGE_OUTPUT"
    (
        cd "$ARCHIVE_DIR"
        ar r "$PACKAGE_OUTPUT" debian-binary control.tar.xz data.tar.xz
    )
fi

echo "Paket erstellt: $PACKAGE_OUTPUT"
