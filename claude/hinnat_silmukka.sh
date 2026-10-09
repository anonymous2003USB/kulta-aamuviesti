#!/usr/bin/env bash
# Hakee kullan kynttilät 5 minuutin välein ja julkaisee ne haaraan "hinnat" (vain viimeisin versio säilyy).
# KERTAA=1: hae kerran. Muuten jatka klo 21.15 Suomen aikaa asti. GitHubin työ saa kestää enintään 6 h,
# joten 5 h 40 min jälkeen työ käynnistää itsensä uudelleen.
set -u
ALKU=$(date +%s)
REMOTE="https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
SKRIPTI="$PWD/claude/hae_hinnat.py"

julkaise() {
  rm -rf /tmp/h && python "$SKRIPTI" /tmp/h || return 1
  (
    cd /tmp/h &&
    git init -q -b hinnat &&
    git add . &&
    git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
        commit -qm "Hinnat $(date -u +%FT%TZ)" &&
    git push -qf "$REMOTE" hinnat
  )
}

while true; do
  julkaise || echo "Haku tai julkaisu epäonnistui, yritetään seuraavalla kierroksella."
  [ "${KERTAA:-0}" = "1" ] && exit 0
  KLO=$(TZ=Europe/Helsinki date +%-H%M)
  [ "$KLO" -ge 2115 ] && exit 0
  if [ $(( $(date +%s) - ALKU )) -gt 20400 ]; then
    gh workflow run hinnat.yml --ref main -R "$GITHUB_REPOSITORY" -f kertaa=0
    exit 0
  fi
  sleep 300
done
