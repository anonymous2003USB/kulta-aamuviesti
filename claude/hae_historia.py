"""Hakee kullan (XAU/USD) minuuttikynttilät (bid ja ask) Dukascopylta annetulle aikavälille.

Käyttö: python hae_historia.py KANSIO ALKU_UTC LOPPU_UTC   (esim. 2026-10-27T00:00:00Z)
Kertahaku puuttuvan jakson täyttämiseen (hintasyöte katkesi 28.10.2026). Haku tehdään vuorokauden paloissa.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import dukascopy_python as d
import pandas as pd

INSTR = "XAU/USD"


def hae(puoli, alku, loppu):
    for yritys in range(5):
        try:
            df = d.fetch(INSTR, d.INTERVAL_MIN_1, puoli, alku, loppu, max_retries=3)
            return df[~df.index.duplicated()].sort_index()[["open", "high", "low", "close", "volume"]]
        except Exception as e:
            print("virhe", puoli, alku, e, file=sys.stderr)
            time.sleep(5 * (yritys + 1))
    raise RuntimeError(f"haku epäonnistui: {puoli} {alku}")


def main(kansio, alku, loppu):
    os.makedirs(kansio, exist_ok=True)
    a0 = datetime.fromisoformat(alku.replace("Z", "+00:00"))
    l0 = datetime.fromisoformat(loppu.replace("Z", "+00:00"))
    rivit = {}
    for puoli, nimi in ((d.OFFER_SIDE_BID, "m1_bid"), (d.OFFER_SIDE_ASK, "m1_ask")):
        osat, t = [], a0
        while t < l0:
            u = min(t + timedelta(days=1), l0)
            if t.weekday() != 5:  # lauantaina markkina kiinni
                df = hae(puoli, t, u)
                if len(df):
                    osat.append(df)
                print(nimi, t.date(), len(df), flush=True)
            t = u
        df = pd.concat(osat)
        df = df[~df.index.duplicated()].sort_index()
        df.round(3).to_csv(f"{kansio}/{nimi}.csv", index_label="timestamp")
        rivit[nimi] = [len(df), df.index[0].isoformat(), df.index[-1].isoformat()]
    meta = dict(haettu_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), alku=alku, loppu=loppu,
                kirjasto="dukascopy-python 4.0.1", rivit=rivit)
    json.dump(meta, open(f"{kansio}/meta.json", "w"), indent=1)
    print(meta)


if __name__ == "__main__":
    main(*sys.argv[1:4])
