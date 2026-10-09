"""Clauden kauppamuisti: kaikki aiemmat kaupat, tulokset ja opit yhdellä silmäyksellä.

Käyttö: python -I muisti.py DBKANSIO [--tanaan YYYY-MM-DD]
DBKANSIO: ArtifactData query out_dir -kansio (kaupat/*.json), haettu ehdolla tekija == "claude".
"""
import glob
import json
import os
import sys

import numpy as np

SMC_ALKAA = "2026-10-12"
MALLIT = {"pyyhkaisy_choch": "Likviditeetin pyyhkäisy + CHoCH", "vyohyke_retesti": "Paluu vyöhykkeelle trendin suuntaan",
          "fvg_jatko": "Paluu FVG:hen BOS:n jälkeen", "muu": "Muu"}


def lue(dbk):
    out = []
    for f in sorted(glob.glob(f"{dbk}/**/*.json", recursive=True)):
        x = json.load(open(f))
        x = x.get("data", x)
        if x.get("tekija") == "claude":
            x["_id"] = os.path.basename(f)[:-5]
            out.append(x)
    return sorted(out, key=lambda x: (x.get("pvm", ""), x.get("klo", "")))


def R(x):
    riski = abs(float(x["entry"]) - float(x["sl"])) * float(x.get("lotit", 0.01)) * 100
    return float(x["tulosValittaja"]) / riski if riski > 0 else np.nan


def tilasto(lista):
    s = [x for x in lista if x.get("tila") == "suljettu" and isinstance(x.get("tulosValittaja"), (int, float))]
    if not s:
        return "0 kauppaa"
    usd = np.array([x["tulosValittaja"] for x in s], float)
    r = np.array([R(x) for x in s], float)
    v, t = usd[usd > 0].sum(), -usd[usd < 0].sum()
    pf = f"{v / t:.2f}" if t > 0 else "∞"
    return (f"{len(s)} kauppaa, voittoja {int((usd > 0).sum())} ({(usd > 0).mean() * 100:.0f} %), "
            f"tulos {usd.sum():+.2f} $, keskim. {np.nanmean(r):+.2f} R, PF {pf}")


def main(dbk, tanaan=None):
    k = lue(dbk)
    print("KAIKKI KAUPPANI")
    print(f"  Yhteensä:            {tilasto(k)}")
    print(f"  Vanha tapa (uutiset): {tilasto([x for x in k if x.get('pvm', '') < SMC_ALKAA])}")
    smc = [x for x in k if x.get("pvm", "") >= SMC_ALKAA]
    print(f"  SMC-tapa:            {tilasto(smc)}")
    for m, nimi in MALLIT.items():
        lst = [x for x in smc if x.get("malli") == m]
        if lst:
            print(f"    {nimi}: {tilasto(lst)}")
    for t, nimi in (("limit", "Limit"), ("markkina", "Markkina")):
        lst = [x for x in smc if x.get("tyyppi", "markkina") == t]
        if lst:
            print(f"    {nimi}: {tilasto(lst)}")
    for s in ("osto", "myynti"):
        lst = [x for x in smc if x.get("suunta") == s]
        if lst:
            print(f"    {s}: {tilasto(lst)}")
    perutut = [x for x in smc if x.get("tila") in ("peruttu", "virheellinen")]
    if perutut:
        print(f"  Peruttuja/virheellisiä toimeksiantoja: {len(perutut)}")
    print("\nVIIMEISET 20 KAUPPAA (vanhin ensin)")
    for x in k[-20:]:
        tulos = f"{x['tulosValittaja']:+.2f} $ ({R(x):+.1f} R, {x.get('syy', '')})" \
            if x.get("tila") == "suljettu" and isinstance(x.get("tulosValittaja"), (int, float)) else x.get("tila", "")
        print(f"  {x.get('pvm')} {x.get('klo')} {x.get('suunta'):6s} {x.get('tyyppi', 'markkina'):8s} "
              f"{x.get('malli', '-'):16s} {tulos}")
        if x.get("setup"):
            print(f"      setup: {x['setup']}")
        if x.get("opetus"):
            print(f"      opetus: {x['opetus']}")
    if tanaan:
        t = [x for x in k if x.get("pvm") == tanaan and x.get("tila") != "virheellinen"]
        tappiot = [x for x in t if x.get("tila") == "suljettu" and x.get("tulosValittaja", 0) < 0]
        auki = [x for x in t if x.get("tila") == "auki"]
        print(f"\nTÄNÄÄN {tanaan}: kirjattu {len(t)} (laskee 3:n rajaan), tappioita {len(tappiot)}, auki/odottaa {len(auki)}")
        for x in auki:
            print(f"  auki: {x['_id']} {x['suunta']} {x.get('tyyppi', 'markkina')} entry {x['entry']} SL {x['sl']} TP {x['tp']}"
                  f"{' voimassa ' + x['voimassa_hki'] if x.get('voimassa_hki') else ''}")
    ilman = [x["_id"] for x in k if x.get("tila") == "suljettu" and not x.get("opetus") and x.get("pvm", "") >= SMC_ALKAA]
    if ilman:
        print(f"\nOPETUS PUUTTUU: {', '.join(ilman)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    t = None
    if "--tanaan" in a:
        i = a.index("--tanaan")
        t = a[i + 1]
        del a[i:i + 2]
    main(a[0], t)
