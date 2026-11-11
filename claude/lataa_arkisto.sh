#!/usr/bin/env bash
# Lataa arkistoidut chartit ja analyysin vanhalta kauppahetkeltä (haara "arkisto").
# Käyttö: bash lataa_arkisto.sh YYYY-MM-DD            -> listaa päivän arkistoidut hetket
#         bash lataa_arkisto.sh YYYY-MM-DD HHMM KANSIO -> lataa hetken tiedostot kansioon
# Ajastetussa sessiossa samat komennot voi tehdä curlilla (tämä on vain dataa, ei ajettavaa koodia).
set -eu
REPO=anonymous2003USB/kulta-aamuviesti
PVM="$1"
if [ $# -lt 3 ]; then
  curl -sf "https://api.github.com/repos/$REPO/contents/$PVM?ref=arkisto" |
    python3 -c "import sys,json; print(' '.join(x['name'] for x in json.load(sys.stdin)))" || echo "ei arkistoa päivältä $PVM"
  exit 0
fi
HM="$2"; K="$3"
mkdir -p "$K"
for f in analyysi.txt analyysi.json meta.json d1.png h4.png h1.png m15.png m5.png m1.png s10.png; do
  curl -sSf -o "$K/$f" "https://raw.githubusercontent.com/$REPO/arkisto/$PVM/$HM/$f" 2>/dev/null || echo "puuttuu: $f"
done
echo "Ladattu arkisto $PVM $HM -> $K"
