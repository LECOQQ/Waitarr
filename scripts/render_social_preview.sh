#!/usr/bin/env bash
# Render docs/assets/social-preview.png (1280x640) from the logo.
#
# Needs ImageMagick 6 built with Pango, and the Noto Color Emoji font for
# the turtle and the bolt. Text uses the Lato files shipped in
# docs/assets/fonts/, declared through a private fontconfig file, so the
# result does not depend on the fonts of the machine.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
assets="$root/docs/assets"
out="${1:-$assets/social-preview.png}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cat > "$work/fonts.conf" <<EOF
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>$assets/fonts</dir>
  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>
  <cachedir>$work/cache</cachedir>
</fontconfig>
EOF
export FONTCONFIG_FILE="$work/fonts.conf"

# Anthracite, like the *arr interfaces; the accent is the logo's play blue.
bg_top='#26292e'
bg_bottom='#181a1e'
accent='#2490fc'
text='#eef0f2'
muted='#a3abb5'

text_png() { # file, pango markup
  convert -background none pango:"$2" "$1"
}

convert -size 1280x640 "gradient:$bg_top-$bg_bottom" "$work/bg.png"
convert "$assets/waitarr-logo.png" -resize 500x500 "$work/logo.png"

text_png "$work/name.png" \
  "<span font='Lato Black 92' foreground='$text'>Wait</span><span font='Lato Black 92' foreground='$accent'>arr</span>"
text_png "$work/slogan.png" \
  "<span font='Lato 34' foreground='$text'>Jellyfin and torrents\non a Raspberry Pi,\nwithout the stutter.</span>"
text_png "$work/mechanism.png" \
  "<span font='Lato 21' foreground='$muted'>▶ play → 🐢 crawl      ⏹ stop → ⚡ full speed</span>"

convert "$work/bg.png" \
  "$work/logo.png" -geometry +70+70 -composite \
  "$work/name.png" -geometry +620+112 -composite \
  "$work/slogan.png" -geometry +622+256 -composite \
  "$work/mechanism.png" -geometry +624+458 -composite \
  -depth 8 -strip -define png:compression-level=9 -define png:compression-strategy=1 \
  "$out"
printf 'Wrote %s\n' "$out"
