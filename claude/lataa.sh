#!/usr/bin/env bash
# Lataa tuoreimmat hinnat hinnat-haarasta kansioon. Käyttö: bash lataa.sh KOHDEKANSIO
# Hakee ensin haaran viimeisimmän version tunnisteen, jotta välimuisti ei anna vanhaa tiedostoa.
set -eu
K="$1"
mkdir -p "$K"
REPO=anonymous2003USB/kulta-aamuviesti
SHA=$(curl -sf "https://api.github.com/repos/$REPO/commits/hinnat" |
      python3 -c "import sys,json; print(json.load(sys.stdin)['sha'])" 2>/dev/null || echo hinnat)
for f in meta.json m1_bid.csv m1_ask.csv h1_bid.csv; do
  curl -sSf -o "$K/$f" "https://raw.githubusercontent.com/$REPO/$SHA/$f"
done
python3 - "$K" "$SHA" <<'EOF'
import json, sys, datetime as d
m = json.load(open(f"{sys.argv[1]}/meta.json"))
t = d.datetime.fromisoformat(m["viimeinen_m1_utc"])
ika = (d.datetime.now(d.timezone.utc) - t).total_seconds() / 60 - 1
print(f"Data ladattu (versio {sys.argv[2][:7]}): viimeinen minuutti {t:%Y-%m-%d %H:%M} UTC, ikä {ika:.0f} min, "
      f"bid {m['bid']} ask {m['ask']}")
EOF
