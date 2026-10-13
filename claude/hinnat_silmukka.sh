#!/usr/bin/env bash
# Hakee kullan kynttilät 1 minuutin välein (välimuistin avulla vain uudet minuutit + 60 min sekuntidataa) ja julkaisee ne haaraan "hinnat" (vain viimeisin versio säilyy).
# Pyörii arkipäivisin yhtäjaksoisesti (ma 00.00 – la 00.00 Suomen aikaa). Haku tehdään klo 01.30–05.00
# (Aasian avaukset) ja 07.00–23.59; muulloin odotetaan. GitHubin työ saa kestää enintään 6 h, joten
# 5 h 40 min jälkeen työ käynnistää itsensä uudelleen. Lauantaina ja sunnuntaina työ päättyy.
# KERTAA=1: hae kerran ja lopeta.
set -u
ALKU=$(date +%s)
REMOTE="https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
SKRIPTI="$PWD/claude/hae_hinnat.py"

ANALYYSI="$PWD/claude/smc.py"
AJAT="$PWD/claude/ajat.py"
ARKISTO="$PWD/claude/arkistoi.py"

julkaise() {
  rm -rf /tmp/h && python "$SKRIPTI" /tmp/h --valimuisti /tmp/hv || return 1
  # Valmis analyysi ja chartit samaan haaraan: ajastetut sessiot lukevat ne datana, koodia ajamatta.
  python "$ANALYYSI" /tmp/h /tmp/h/anal > /tmp/h/anal_tuloste.txt 2>&1
  echo "paluukoodi $?" >> /tmp/h/anal_tuloste.txt
  mv /tmp/h/anal_tuloste.txt /tmp/h/anal/analyysi_tuloste.txt 2>/dev/null || true
  { python "$AJAT"; echo "--- Aasia"; python "$AJAT" --aasia; } > /tmp/h/ajat.txt 2>&1 || true
  (
    cd /tmp/h &&
    git init -q -b hinnat &&
    git add . &&
    git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
        commit -qm "Hinnat $(date -u +%FT%TZ)" &&
    git push -qf "$REMOTE" hinnat
  )
  # kauppahetkien chartit pysyvästi talteen (arkisto-haara), ei kaada syötettä jos epäonnistuu
  python "$ARKISTO" /tmp/h || true
}

jatka() {
  for i in 1 2 3; do
    gh workflow run hinnat.yml --ref main -R "$GITHUB_REPOSITORY" -f kertaa=0 && return 0
    sleep 20
  done
  echo "Uudelleenkäynnistys epäonnistui."
}

if [ "${KERTAA:-0}" = "1" ]; then
  julkaise
  exit $?
fi

while true; do
  PV=$(TZ=Europe/Helsinki date +%u)   # 1 = maanantai ... 7 = sunnuntai
  KLO=$((10#$(TZ=Europe/Helsinki date +%H%M)))
  if [ "$PV" -ge 6 ]; then
    echo "Viikonloppu: markkina kiinni."
    exit 0
  fi
  if { [ "$KLO" -ge 130 ] && [ "$KLO" -lt 500 ]; } || [ "$KLO" -ge 700 ]; then
    julkaise || echo "Haku tai julkaisu epäonnistui, yritetään seuraavalla kierroksella."
  fi
  if [ $(( $(date +%s) - ALKU )) -gt 20400 ]; then
    jatka
    exit 0
  fi
  sleep $(( 60 - $(date +%s) % 60 ))   # seuraavan minuutin alkuun
done
