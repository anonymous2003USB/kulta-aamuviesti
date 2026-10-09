"""Ratkaisee Clauden auki olevat kaupat minuuttidatalla ja tekee päiväkirjan päivitykset valmiiksi.

Käyttö:
  python -I ratkaise.py DATAKANSIO DBKANSIO ULOSKANSIO --versiot "doc_id=versio,doc_id=versio"
DATAKANSIO: m1_bid.csv ja m1_ask.csv (hae_hinnat.py)
DBKANSIO:   ArtifactData query out_dir -kansio (sisältää kaupat/*.json)
--versiot:  dokumenttien versiot query-tuloksen listasta (tarvitaan if_version-kenttään)
Tuottaa ULOSKANSIOON jokaisesta muuttuvasta kaupasta <doc_id>.json ja tiedoston writes.json,
jonka sisällön voi antaa sellaisenaan ArtifactData batch -kutsun writes-kenttään.
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import moottori as M  # noqa: E402

HKI = "Europe/Helsinki"


def hki(iso):
    return pd.Timestamp(iso).tz_convert(HKI)


def main(data, dbk, ulos, versiot):
    os.makedirs(ulos, exist_ok=True)
    H = M.Hinnat(f"{data}/m1_bid.csv", f"{data}/m1_ask.csv")
    nyt = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    writes, rivit = [], []
    for f in sorted(glob.glob(f"{dbk}/**/*.json", recursive=True)):
        doc_id = os.path.basename(f)[:-5]
        x = json.load(open(f))
        x = x.get("data", x)
        if x.get("tekija") != "claude" or x.get("tila") != "auki":
            continue
        r = M.ratkaise_kauppa(H, x)
        d = {}
        if r["tila"] == "suljettu":
            ex = hki(r["exit_utc"])
            d = dict(tila="suljettu", exit=float(r["exit"]), syy=r["syy"], taytto=float(r["taytto"]),
                     tulosValittaja=float(r["tulos_usd"]), suljettuPvm=ex.strftime("%Y-%m-%d"),
                     suljettu=ex.isoformat(timespec="minutes"), taytto_utc=r["taytto_utc"], exit_utc=r["exit_utc"],
                     ratkaistu=f"minuuttidata {nyt}")
            if "huom" in r:
                d["huom"] = r["huom"]
            rivit.append(f"{doc_id}: {x['suunta']} {x.get('tyyppi', 'markkina')} täyttö {r['taytto']} -> {r['syy'].upper()} "
                         f"{ex:%d.%m. %H:%M} tulos {r['tulos_usd']:+.2f} $ (vastakkainen suunta olisi {r['vastakkainen_usd']:+.2f} $)")
        elif r["tila"] in ("peruttu", "virheellinen"):
            d = dict(tila=r["tila"], huom=r.get("huom", ""), ratkaistu=f"minuuttidata {nyt}")
            if "taytto" in r:
                d["taytto"] = float(r["taytto"])
            rivit.append(f"{doc_id}: {r['tila'].upper()}: {r.get('huom', '')}")
        elif r.get("taytto") is not None and x.get("taytto") is None:
            d = dict(taytto=float(r["taytto"]), taytto_utc=r["taytto_utc"])
            rivit.append(f"{doc_id}: täyttyi {r['taytto']} ({hki(r['taytto_utc']):%d.%m. %H:%M}), vielä auki")
        else:
            rivit.append(f"{doc_id}: auki ({r.get('huom', '')})")
        if d:
            polku = os.path.abspath(f"{ulos}/{doc_id}.json")
            json.dump(d, open(polku, "w"), ensure_ascii=False, indent=1)
            w = dict(op="update", collection="kaupat", doc_id=doc_id, file_path=polku)
            if doc_id not in versiot:
                rivit.append(f"  HUOM: versio puuttuu kaupalle {doc_id}; anna se --versiot-listassa")
            else:
                w["if_version"] = versiot[doc_id]
            writes.append(w)
    json.dump(writes, open(f"{ulos}/writes.json", "w"), ensure_ascii=False, indent=1)
    print("\n".join(rivit) if rivit else "Ei auki olevia Clauden kauppoja.")
    print(f"\n{len(writes)} päivitystä: {os.path.abspath(ulos)}/writes.json")
    print(json.dumps(writes, ensure_ascii=False))


if __name__ == "__main__":
    a = sys.argv[1:]
    v = {}
    if "--versiot" in a:
        i = a.index("--versiot")
        for pari in a[i + 1].split(","):
            if "=" in pari:
                k, n = pari.strip().split("=")
                v[k.strip()] = int(n)
        del a[i:i + 2]
    main(a[0], a[1], a[2], v)
