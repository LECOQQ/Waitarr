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
pill_fill='#2c3036'
pill_line='#3d434b'

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

pills=("Jellyfin" "qBittorrent" "Docker" "amd64 / arm64")
row=()
for i in "${!pills[@]}"; do
  text_png "$work/label$i.png" \
    "<span font='Lato Bold 15' foreground='$muted'>${pills[$i]}</span>"
  read -r w h < <(identify -format '%w %h\n' "$work/label$i.png")
  pw=$((w + 32))
  ph=$((h + 14))
  convert -size "${pw}x${ph}" xc:none -fill "$pill_fill" -stroke "$pill_line" \
    -strokewidth 1.5 -draw "roundrectangle 1,1 $((pw - 2)),$((ph - 2)) $((ph / 2)),$((ph / 2))" \
    "$work/label$i.png" -gravity center -composite "$work/pill$i.png"
  row+=("$work/pill$i.png")
  if [ "$i" -lt $((${#pills[@]} - 1)) ]; then
    text_png "$work/sep$i.png" "<span font='Lato 18' foreground='$pill_line'> – </span>"
    row+=("$work/sep$i.png")
  fi
done
convert -background none "${row[@]}" -gravity center +append "$work/pills.png"

convert "$work/bg.png" \
  "$work/logo.png" -geometry +70+50 -composite \
  "$work/name.png" -geometry +620+92 -composite \
  "$work/slogan.png" -geometry +622+236 -composite \
  "$work/mechanism.png" -geometry +624+438 -composite \
  "$work/pills.png" -gravity south -geometry +0+40 -composite \
  -depth 8 -strip -define png:compression-level=9 -define png:compression-strategy=1 \
  "$out"
printf 'Wrote %s\n' "$out"
