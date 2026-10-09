"""Testit Clauden analyysi- ja ratkaisutyökaluille. Käyttö: python -I testit.py DATAKANSIO
DATAKANSIO = hae_hinnat.py:n tuottama kansio (oikeaa dataa). Tulostaa OK/VIRHE jokaisesta testistä.
"""
import json
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smc  # noqa: E402
import moottori as M  # noqa: E402

virheita = 0


def ok(nimi, ehto, lisa=""):
    global virheita
    print(("OK    " if ehto else "VIRHE ") + nimi + (f"  ({lisa})" if lisa else ""))
    virheita += 0 if ehto else 1


def kk(rivit, alku="2026-01-05 10:00", vali="1h"):
    idx = pd.date_range(alku, periods=len(rivit), freq=vali, tz="UTC")
    return pd.DataFrame(rivit, columns=["open", "high", "low", "close"], index=idx, dtype=float)


def test_rakenne():
    # nousu swing high 110 (i=3), lasku swing low 100 (i=6), sulku 111 -> BOS/CHoCH ylös
    r = [(100, 101, 99, 100), (100, 104, 99, 103), (103, 107, 102, 106), (106, 110, 105, 107),
         (107, 108, 104, 105), (105, 106, 102, 103), (103, 104, 100, 101), (101, 103, 100.5, 102),
         (102, 105, 101, 104), (104, 108, 103, 107), (107, 112, 106, 111), (111, 113, 110, 112)]
    k = kk(r)
    sw = smc.swingit(k, 2)
    ok("swing high löytyy oikeasta kohdasta", (3, "H", 110.0) in sw, sw)
    ok("swing low löytyy oikeasta kohdasta", (6, "L", 100.0) in sw, sw)
    tr, tap, _ = smc.rakenne(k, 2)
    ylos = [e for e in tap if e["suunta"] == 1]
    ok("murto ylös kynttilällä 10 (sulku 111 > 110)", bool(ylos) and ylos[0]["j"] == 10 and ylos[0]["taso"] == 110, tap)
    ok("trendi nousu", tr == 1)
    # swing ei saa olla tiedossa ennen kuin 2 kynttilää sen jälkeen on sulkeutunut
    tr2, tap2, _ = smc.rakenne(k.iloc[:5], 2)
    ok("ei tulevaisuuden tietoa (swing 3 ei vielä vahvistunut kynttilällä 4)", all(e["swing_i"] != 3 for e in tap2))


def test_fvg():
    r = [(100, 102, 99, 101), (101, 108, 101, 107), (107, 110, 104, 109), (109, 110, 103, 104)]
    k = kk(r)
    f = smc.fvgt(k, 5.0)
    nous = [x for x in f if x["suunta"] == 1]
    ok("nouseva FVG 102–104", bool(nous) and nous[0]["ala"] == 102 and nous[0]["yla"] == 104, f)
    ok("FVG osittain täytetty (low 103)", bool(nous) and nous[0]["osittain"] and not nous[0]["taytetty"])


def test_ei_tulevaa(kansio):
    b = smc.lue(f"{kansio}/m1_bid.csv")
    hetket = [b.index[len(b) // 2], b.index[int(len(b) * 0.8)], b.index[-200]]
    for t in hetket:
        t = t.ceil("15min")
        thki = t.tz_convert(smc.HKI).strftime("%Y-%m-%d %H:%M")
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(f"{d}/lyhyt")
            for nimi, kesto in (("m1_bid", "1min"), ("m1_ask", "1min"), ("h1_bid", "1h")):
                x = pd.read_csv(f"{kansio}/{nimi}.csv")
                ts = pd.to_datetime(x.timestamp, utc=True)
                x[ts + pd.Timedelta(kesto) <= t].to_csv(f"{d}/lyhyt/{nimi}.csv", index=False)
            with open(os.devnull, "w") as nul:
                vanha = sys.stdout
                sys.stdout = nul
                try:
                    smc.analysoi(kansio, f"{d}/a", thki)
                    smc.analysoi(f"{d}/lyhyt", f"{d}/b", thki)
                finally:
                    sys.stdout = vanha
            ja = json.load(open(f"{d}/a/analyysi.json"))
            jb = json.load(open(f"{d}/b/analyysi.json"))
            for j in (ja, jb):
                j.pop("huomiot")
            ok(f"sama analyysi koko datalla ja {thki} katkaistulla datalla", ja == jb)


def test_aikavyohykevirhe(kansio):
    b, a, h = (smc.lue(f"{kansio}/{n}.csv") for n in ("m1_bid", "m1_ask", "h1_bid"))
    v, _ = smc.tarkista(b, a, h)
    ok("oikea data läpäisee tarkistuksen", not v, v)
    b2, a2 = b.copy(), a.copy()
    b2.index, a2.index = b2.index + pd.Timedelta(hours=1), a2.index + pd.Timedelta(hours=1)
    v2, _ = smc.tarkista(b2, a2, h)
    ok("tunnin aikasiirtymä huomataan", any("H1" in x for x in v2), v2)
    nyt = b.index[-1] + pd.Timedelta(minutes=40)
    v3, _ = smc.tarkista(b, a, h, nyt if nyt.tz_convert(smc.NY).weekday() < 4 else b.index[-1] + pd.Timedelta(minutes=40))
    ok("40 min vanha data hylätään markkinan ollessa auki",
       any("VANHA" in x for x in v3) or nyt.tz_convert(smc.NY).weekday() >= 4, v3)


def test_moottori():
    # minuuttidata: bid = ask - 0.3
    t0 = pd.Timestamp("2026-01-06 09:00", tz="UTC")
    n = 120
    idx = pd.date_range(t0, periods=n, freq="1min")
    hinta = np.full(n, 2000.0)
    hinta[10:20] = 1995  # pudotus
    hinta[30:] = 2012    # nousu
    d = tempfile.mkdtemp()
    for nimi, lisa in (("bid", 0.0), ("ask", 0.3)):
        pd.DataFrame(dict(timestamp=idx, open=hinta + lisa, high=hinta + lisa + 0.5, low=hinta + lisa - 0.5,
                          close=hinta + lisa)).to_csv(f"{d}/{nimi}.csv", index=False)
    H = M.Hinnat(f"{d}/bid.csv", f"{d}/ask.csv")
    # markkinaosto 09:00: täyttö ask 2000.3, SL 10 $ alle, TP 10 $ yli -> TP osuu (bid high 2012.5)
    r = M.ratkaise_kauppa(H, dict(suunta="osto", tyyppi="markkina", aika_utc="2026-01-06T09:00:00Z",
                                  entry=2000.3, sl=1990.3, tp=2010.3))
    ok("markkinaosto -> TP", r["tila"] == "suljettu" and r["syy"] == "tp" and abs(r["tulos_oz"] - 10) < 1e-9, r)
    # limit-osto 1995.5: ask low 1994.8 kynttilöillä 10-19 -> täyttyy klo 09:10, SL 1985 ei osu, TP 2005 osuu
    r = M.ratkaise_kauppa(H, dict(suunta="osto", tyyppi="limit", aika_utc="2026-01-06T09:01:00Z",
                                  entry=1995.5, sl=1985.5, tp=2005.5, voimassa_utc="2026-01-06T10:00:00Z"))
    ok("limit-osto täyttyy ja -> TP", r["tila"] == "suljettu" and r["syy"] == "tp" and r["taytto_utc"].startswith("2026-01-06T09:10"), r)
    # limit-osto 1990, ei koskaan täyty -> peruttu
    r = M.ratkaise_kauppa(H, dict(suunta="osto", tyyppi="limit", aika_utc="2026-01-06T09:01:00Z",
                                  entry=1990, sl=1980, tp=2010, voimassa_utc="2026-01-06T10:30:00Z"))
    ok("täyttymätön limit -> peruttu", r["tila"] == "peruttu", r)
    # limit-myynti 2011, TP 1999: TP-taso 1999 kosketetaan (bid low 1994.5 klo 09:10) ennen täyttöä -> peruttu
    r = M.ratkaise_kauppa(H, dict(suunta="myynti", tyyppi="limit", aika_utc="2026-01-06T09:01:00Z",
                                  entry=2011, sl=2021, tp=1999, voimassa_utc="2026-01-06T10:30:00Z"))
    ok("limit peruuntuu, jos TP-taso saavutetaan ennen täyttöä", r["tila"] == "peruttu", r)
    # markkinamyynti 09:05: täyttö bid 2000, SL 2010 osuu (nousu 2012) ennen TP 1980
    r = M.ratkaise_kauppa(H, dict(suunta="myynti", tyyppi="markkina", aika_utc="2026-01-06T09:05:00Z",
                                  entry=2000, sl=2010, tp=1980))
    ok("markkinamyynti -> SL", r["tila"] == "suljettu" and r["syy"] == "sl" and r["tulos_oz"] < -9.9, r)
    # data loppuu ennen aikarajaa -> auki
    r = M.ratkaise_kauppa(H, dict(suunta="osto", tyyppi="markkina", aika_utc="2026-01-06T09:40:00Z",
                                  entry=2012.3, sl=2002.3, tp=2032.3))
    ok("kesken jäänyt kauppa pysyy auki", r["tila"] == "auki", r)
    shutil.rmtree(d)


def test_tarkistin():
    perus = dict(suunta="osto", tyyppi="markkina", entry=2000.3, sl=1990.3, tp=2020.3)
    tila = dict(bid=2000.0, ask=2000.3, datan_ika_min=3, nyt_hki="2026-01-06 12:00", kauppoja_tanaan=0,
                tappioita_tanaan=0, julkaisut=[])
    ok("hyvä kauppa hyväksytään", M.tarkista_kauppa(perus, tila) == [], M.tarkista_kauppa(perus, tila))
    ok("SL väärällä puolella hylätään", M.tarkista_kauppa({**perus, "sl": 2010.3}, tila) != [])
    ok("RR alle 2 hylätään", M.tarkista_kauppa({**perus, "tp": 2010.3}, tila) != [])
    ok("liian iso SL hylätään", M.tarkista_kauppa({**perus, "sl": 1960.3, "tp": 2080.3}, tila) != [])
    ok("vanha data hylätään", M.tarkista_kauppa(perus, {**tila, "datan_ika_min": 25}) != [])
    ok("4. kauppa hylätään", M.tarkista_kauppa(perus, {**tila, "kauppoja_tanaan": 3}) != [])
    ok("2 tappion jälkeen hylätään", M.tarkista_kauppa(perus, {**tila, "tappioita_tanaan": 2}) != [])
    ok("julkaisun lähellä markkinakauppa hylätään",
       M.tarkista_kauppa(perus, {**tila, "julkaisut": ["12:15"]}) != [])
    lim = dict(suunta="osto", tyyppi="limit", entry=1995, sl=1987, tp=2011, voimassa_hki="2026-01-06 16:00")
    ok("limit-osto markkinan alla hyväksytään", M.tarkista_kauppa(lim, tila) == [], M.tarkista_kauppa(lim, tila))
    ok("limit-osto markkinan yllä hylätään", M.tarkista_kauppa({**lim, "entry": 2005, "sl": 1997, "tp": 2021}, tila) != [])
    ok("limit, jonka voimassaolo yli klo 21.00, hylätään",
       M.tarkista_kauppa({**lim, "voimassa_hki": "2026-01-06 22:00"}, tila) != [])


if __name__ == "__main__":
    test_rakenne()
    test_fvg()
    test_moottori()
    test_tarkistin()
    if len(sys.argv) > 1:
        test_aikavyohykevirhe(sys.argv[1])
        test_ei_tulevaa(sys.argv[1])
    print(f"\n{virheita} virhettä")
    sys.exit(1 if virheita else 0)
