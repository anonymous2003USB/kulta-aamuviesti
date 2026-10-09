"""Hakee kullan (XAU/USD) kynttilät Dukascopylta Clauden analyysiä ja kauppojen ratkaisua varten.

Kirjoittaa kansioon:
  m1_bid.csv, m1_ask.csv  minuuttikynttilät, viimeiset 8 päivää (kauppojen ratkaisu, M5/M15-analyysi)
  h1_bid.csv              tuntikynttilät, viimeiset 150 päivää (H1/H4/D-rakenne)
  meta.json               hakuaika ja viimeisin hinta
Käyttö: python hae_hinnat.py kansio
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import dukascopy_python as d

INSTR = "XAU/USD"


def hae(vali, puoli, paivia):
    nyt = datetime.now(timezone.utc)
    for yritys in range(4):
        try:
            df = d.fetch(INSTR, vali, puoli, nyt - timedelta(days=paivia), nyt, max_retries=3)
            if len(df):
                df = df[~df.index.duplicated()].sort_index()
                return df[["open", "high", "low", "close", "volume"]]
        except Exception as e:  # verkkovirhe: yritä uudelleen
            print("virhe", vali, puoli, e, file=sys.stderr)
        time.sleep(5 * (yritys + 1))
    raise RuntimeError(f"haku epäonnistui: {vali} {puoli}")


def main(kansio):
    os.makedirs(kansio, exist_ok=True)
    b = hae(d.INTERVAL_MIN_1, d.OFFER_SIDE_BID, 8)
    a = hae(d.INTERVAL_MIN_1, d.OFFER_SIDE_ASK, 8)
    h = hae(d.INTERVAL_HOUR_1, d.OFFER_SIDE_BID, 150)
    for df, nimi in ((b, "m1_bid"), (a, "m1_ask"), (h, "h1_bid")):
        df.round(3).to_csv(f"{kansio}/{nimi}.csv", index_label="timestamp")
    meta = dict(
        haettu_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        viimeinen_m1_utc=b.index[-1].isoformat(),
        bid=float(b.close.iloc[-1]),
        ask=float(a.close.iloc[-1]),
        rivit=dict(m1_bid=len(b), m1_ask=len(a), h1_bid=len(h)),
    )
    json.dump(meta, open(f"{kansio}/meta.json", "w"), indent=1)
    print(meta)


if __name__ == "__main__":
    main(sys.argv[1])
