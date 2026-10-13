"""Hakee kullan (XAU/USD) kynttilät Dukascopylta Clauden analyysiä ja kauppojen ratkaisua varten.

Kirjoittaa kansioon:
  m1_bid.csv, m1_ask.csv  minuuttikynttilät, viimeiset 8 päivää (kauppojen ratkaisu, M1/M5/M15-analyysi)
  h1_bid.csv              tuntikynttilät, viimeiset 150 päivää (H1/H4/D-rakenne)
  s10_bid.csv, s10_ask.csv  10 sekunnin kynttilät, viimeinen 60 min (sekuntichartti, tuorein hinta)
  meta.json               hakuaika ja viimeisin hinta
Käyttö: python hae_hinnat.py KANSIO [--valimuisti VKANSIO]
Välimuistin kanssa haetaan vain uudet minuutit (edellisestä hausta lähtien), joten haku on nopea ja
voidaan tehdä minuutin välein. Tuntikynttilät haetaan uudelleen tunnin välein.
"""
import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone

import dukascopy_python as d
import pandas as pd

INSTR = "XAU/USD"
M1_PAIVIA = 8
H1_PAIVIA = 150


def hae(vali, puoli, alku, loppu):
    for yritys in range(4):
        try:
            df = d.fetch(INSTR, vali, puoli, alku, loppu, max_retries=3)
            if len(df):
                df = df[~df.index.duplicated()].sort_index()
                return df[["open", "high", "low", "close", "volume"]]
        except Exception as e:  # verkkovirhe: yritä uudelleen
            print("virhe", vali, puoli, e, file=sys.stderr)
        time.sleep(3 * (yritys + 1))
    raise RuntimeError(f"haku epäonnistui: {vali} {puoli}")


def lue(polku):
    df = pd.read_csv(polku)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.set_index("timestamp")


def yhdista(vanha, uusi, raja):
    """Uudet rivit korvaavat päällekkäiset (keskeneräinen minuutti päivittyy), vanhimmat karsitaan."""
    df = pd.concat([vanha[vanha.index < uusi.index[0]], uusi])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df[df.index >= raja]


def main(kansio, valimuisti=None):
    nyt = datetime.now(timezone.utc)
    vm = valimuisti or kansio
    os.makedirs(vm, exist_ok=True)
    raja_m1 = pd.Timestamp(nyt - timedelta(days=M1_PAIVIA))

    m1 = {}
    for puoli, nimi in ((d.OFFER_SIDE_BID, "m1_bid"), (d.OFFER_SIDE_ASK, "m1_ask")):
        polku = f"{vm}/{nimi}.csv"
        vanha = lue(polku) if os.path.exists(polku) else None
        if vanha is not None and len(vanha) and vanha.index[-1] > pd.Timestamp(nyt - timedelta(days=2)):
            # vain uudet minuutit: 10 min päällekkäisyys, jotta keskeneräinen minuutti päivittyy
            alku = (vanha.index[-1] - pd.Timedelta(minutes=10)).to_pydatetime()
            m1[nimi] = yhdista(vanha, hae(d.INTERVAL_MIN_1, puoli, alku, nyt), raja_m1)
        else:
            m1[nimi] = hae(d.INTERVAL_MIN_1, puoli, nyt - timedelta(days=M1_PAIVIA), nyt)

    h1_polku = f"{vm}/h1_bid.csv"
    if os.path.exists(h1_polku) and time.time() - os.path.getmtime(h1_polku) < 3600:
        h1 = lue(h1_polku)
    else:
        h1 = hae(d.INTERVAL_HOUR_1, d.OFFER_SIDE_BID, nyt - timedelta(days=H1_PAIVIA), nyt)
        h1.round(3).to_csv(h1_polku, index_label="timestamp")

    try:
        s10 = hae(d.INTERVAL_SEC_10, d.OFFER_SIDE_BID, nyt - timedelta(minutes=60), nyt)
        s10a = hae(d.INTERVAL_SEC_10, d.OFFER_SIDE_ASK, nyt - timedelta(minutes=60), nyt)
    except RuntimeError as e:  # sekuntidata on lisätieto: sen puuttuminen ei estä muuta
        print("sekuntidata puuttuu:", e, file=sys.stderr)
        s10 = s10a = None

    for nimi, df in m1.items():
        df.round(3).to_csv(f"{vm}/{nimi}.csv", index_label="timestamp")
    for df, nimi in ((s10, "s10_bid"), (s10a, "s10_ask")):
        if df is not None:
            df.round(3).to_csv(f"{vm}/{nimi}.csv", index_label="timestamp")
        elif os.path.exists(f"{vm}/{nimi}.csv"):
            os.remove(f"{vm}/{nimi}.csv")

    if os.path.abspath(vm) != os.path.abspath(kansio):
        os.makedirs(kansio, exist_ok=True)
        for f in ("m1_bid.csv", "m1_ask.csv", "h1_bid.csv", "s10_bid.csv", "s10_ask.csv"):
            if os.path.exists(f"{vm}/{f}"):
                shutil.copy(f"{vm}/{f}", f"{kansio}/{f}")

    b, a = m1["m1_bid"], m1["m1_ask"]
    meta = dict(
        haettu_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        viimeinen_m1_utc=b.index[-1].isoformat(),
        viimeinen_s10_utc=s10.index[-1].isoformat() if s10 is not None and len(s10) else None,
        bid=float(b.close.iloc[-1]),
        ask=float(a.close.iloc[-1]),
        rivit=dict(m1_bid=len(b), m1_ask=len(a), h1_bid=len(h1), s10_bid=0 if s10 is None else len(s10)),
    )
    json.dump(meta, open(f"{kansio}/meta.json", "w"), indent=1)
    print(meta)


if __name__ == "__main__":
    args = sys.argv[1:]
    vm = None
    if "--valimuisti" in args:
        i = args.index("--valimuisti")
        vm = args[i + 1]
        del args[i:i + 2]
    main(args[0], vm)
