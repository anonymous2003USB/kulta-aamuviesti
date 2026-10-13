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


def test_kynttilakuviot():
    # 0: laskeva 105->102, 1: nouseva 101->106 nielee rungon 102–105 -> nouseva nielevä
    k = kk([(104, 104, 104, 104), (105, 105.5, 101.5, 102), (101, 106.5, 100.5, 106)])
    x = smc.kynttilakuviot(k, 4.0)
    ok("nouseva nielevä tunnistetaan", any(e["kuvio"] == "nielevä" and e["suunta"] == 1 and e["i"] == 2 for e in x), x)
    # pin bar: runko 100–100.5, alavarjo 94 asti (6 $), yläreuna 101, ATR 4 -> nouseva pin bar
    k2 = kk([(100, 102, 98, 101), (100, 101, 94, 100.5)])
    x2 = smc.kynttilakuviot(k2, 4.0)
    ok("nouseva pin bar tunnistetaan", any(e["kuvio"] == "pin bar" and e["suunta"] == 1 for e in x2), x2)
    ok("pin bar ei ole nielevä", not any(e["kuvio"] == "nielevä" for e in x2), x2)
    # laskeva pin bar: yläpuolinen varjo
    k3 = kk([(100, 102, 98, 101), (100.5, 106, 99.5, 100)])
    x3 = smc.kynttilakuviot(k3, 4.0)
    ok("laskeva pin bar tunnistetaan", any(e["kuvio"] == "pin bar" and e["suunta"] == -1 for e in x3), x3)
    # liian pieni kynttilä (koko 1 < 0.5 x ATR 4) ei ole pin bar
    k4 = kk([(100, 102, 98, 101), (100, 100.1, 99, 100.05)])
    ok("pieni kynttilä ei ole pin bar", not any(e["kuvio"] == "pin bar" for e in smc.kynttilakuviot(k4, 4.0)))
    ok("sisäpäivä tunnistetaan", any(e["kuvio"] == "sisäpäivä" for e in smc.kynttilakuviot(k4, 4.0)))


def test_yhdista():
    import hae_hinnat as HH
    vanha = kk([(1, 1, 1, 1), (2, 2, 2, 2), (3, 3, 3, 3), (4, 4, 4, 4)], vali="1min")
    uusi = kk([(30, 30, 30, 30), (5, 5, 5, 5)], alku="2026-01-05 10:03", vali="1min")
    m = HH.yhdista(vanha, uusi, pd.Timestamp("2026-01-05 10:01", tz="UTC"))
    ok("yhdistys: vanhin karsittu, keskeneräinen minuutti päivittyy, uusi lisätty",
       list(m.close) == [2, 3, 30, 5] and m.index.is_unique and m.index.is_monotonic_increasing, list(m.close))


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
    # julkaisun lähellä: täyttö minuutin huonoimpaan hintaan (osto ask high 2000.8)
    r = M.ratkaise_kauppa(H, dict(suunta="osto", tyyppi="markkina", aika_utc="2026-01-06T09:00:00Z", lahella_julkaisua=True,
                                  entry=2000.3, sl=1990.3, tp=2010.3))
    ok("julkaisukauppa täyttyy minuutin huonoimpaan hintaan", r.get("taytto") == 2000.8, r)
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
    ok("6. kauppa hyväksytään", M.tarkista_kauppa(perus, {**tila, "kauppoja_tanaan": 5}) == [])
    ok("7. kauppa hylätään", M.tarkista_kauppa(perus, {**tila, "kauppoja_tanaan": 6}) != [])
    ok("2 tappion jälkeen hyväksytään", M.tarkista_kauppa(perus, {**tila, "tappioita_tanaan": 2}) == [])
    ok("3 tappion jälkeen hylätään", M.tarkista_kauppa(perus, {**tila, "tappioita_tanaan": 3}) != [])
    ok("julkaisun lähellä ilman merkintää hylätään",
       M.tarkista_kauppa(perus, {**tila, "julkaisut": ["12:10"]}) != [])
    ok("julkaisun lähellä merkinnällä hyväksytään",
       M.tarkista_kauppa({**perus, "lahella_julkaisua": True}, {**tila, "julkaisut": ["12:10"]}) == [])
    ok("julkaisu 30 min päässä ei vaadi merkintää", M.tarkista_kauppa(perus, {**tila, "julkaisut": ["12:30"]}) == [])
    lim = dict(suunta="osto", tyyppi="limit", entry=1995, sl=1987, tp=2011, voimassa_hki="2026-01-06 16:00")
    ok("limit-osto markkinan alla hyväksytään", M.tarkista_kauppa(lim, tila) == [], M.tarkista_kauppa(lim, tila))
    ok("limit-osto markkinan yllä hylätään", M.tarkista_kauppa({**lim, "entry": 2005, "sl": 1997, "tp": 2021}, tila) != [])
    ok("limit, jonka voimassaolo yli 4 h, hylätään",
       M.tarkista_kauppa({**lim, "voimassa_hki": "2026-01-06 17:00"}, tila) != [])
    ilta = {**tila, "nyt_hki": "2026-01-06 21:00"}
    ok("klo 21 kauppa hyväksytään", M.tarkista_kauppa(perus, ilta) == [], M.tarkista_kauppa(perus, ilta))
    ok("limit klo 23.30 asti hyväksytään", M.tarkista_kauppa({**lim, "voimassa_hki": "2026-01-06 23:30"}, ilta) == [])
    ok("limit yli klo 23.30 hylätään", M.tarkista_kauppa({**lim, "voimassa_hki": "2026-01-06 23:45"}, ilta) != [])
    ok("klo 3 kauppa hylätään (Aasian seuranta)", M.tarkista_kauppa(perus, {**tila, "nyt_hki": "2026-01-06 03:00"}) != [])
    t = pd.Timestamp("2026-10-12 19:10", tz="UTC")  # 22.10 Suomen aikaa
    ok("uusi aikaraja klo 23.55", M.aikaraja(t, True) == pd.Timestamp("2026-10-12 23:55", tz=M.TZ))
    ok("vanha aikaraja klo 23.00", M.aikaraja(t, False) == pd.Timestamp("2026-10-12 23:00", tz=M.TZ))


def test_pieni_vastaa_moottoria(kansio):
    """Ajastettujen sessioiden pieni.py:n pitää ratkaista kaupat täsmälleen kuten moottori.py."""
    import random
    import pieni as P
    HP = P.Hinnat(f"{kansio}/m1_bid.csv", f"{kansio}/m1_ask.csv")
    HM = M.Hinnat(f"{kansio}/m1_bid.csv", f"{kansio}/m1_ask.csv")
    rnd = random.Random(7)
    erot = 0
    for _ in range(300):
        j = rnd.randrange(0, len(HP.t) - 60)
        u = rnd.choice(["osto", "myynti"])
        tyyppi = rnd.choice(["markkina", "limit"])
        k = 1 if u == "osto" else -1
        hinta = float(HP.ao[j] if u == "osto" else HP.bo[j])
        s, r = rnd.uniform(5, 30), rnd.uniform(2, 4)
        e = hinta - k * rnd.uniform(0, 15) if tyyppi == "limit" else hinta + rnd.uniform(-3, 3)
        x = dict(suunta=u, tyyppi=tyyppi, aika_utc=HP.t[j].isoformat(), entry=round(e, 2), sl=round(e - k * s, 2),
                 tp=round(e + k * s * r, 2), pvm=rnd.choice(["2026-10-09", "2026-10-12"]), lotit=0.01,
                 lahella_julkaisua=rnd.random() < 0.2)
        if tyyppi == "limit":
            x["voimassa_hki"] = (HP.t[j] + pd.Timedelta(hours=rnd.uniform(0.5, 4))).tz_convert(smc.HKI).strftime("%Y-%m-%d %H:%M")
        a, b = P.ratkaise_kauppa(HP, x), M.ratkaise_kauppa(HM, x)
        if a["tila"] != b["tila"] or a.get("exit") != b.get("exit") or a.get("tulos_usd") != b.get("tulos_usd"):
            erot += 1
    ok("pieni.py ratkaisee 300 satunnaista kauppaa samoin kuin moottori.py", erot == 0, f"{erot} eroa")
    perus = dict(suunta="osto", tyyppi="markkina", entry=2000.3, sl=1990.3, tp=2020.3)
    tila = dict(bid=2000.0, ask=2000.3, datan_ika_min=3, nyt_hki="2026-01-06 12:00", kauppoja_tanaan=0,
                tappioita_tanaan=0, julkaisut=[])
    tapaukset = [perus, {**perus, "sl": 2010.3}, {**perus, "tp": 2010.3}, {**perus, "sl": 1960.3, "tp": 2080.3}]
    tilat = [tila, {**tila, "datan_ika_min": 25}, {**tila, "kauppoja_tanaan": 6}, {**tila, "tappioita_tanaan": 3},
             {**tila, "julkaisut": ["12:10"]}, {**tila, "nyt_hki": "2026-01-06 03:00"}]
    samat = all((P.tarkista_kauppa(kk, tt) == []) == (M.tarkista_kauppa(kk, tt) == []) for kk in tapaukset for tt in tilat)
    ok("pieni.py:n tarkistus hyväksyy ja hylkää samat kaupat kuin moottori.py", samat)


if __name__ == "__main__":
    test_rakenne()
    test_fvg()
    test_kynttilakuviot()
    test_yhdista()
    test_moottori()
    test_tarkistin()
    if len(sys.argv) > 1:
        test_aikavyohykevirhe(sys.argv[1])
        test_ei_tulevaa(sys.argv[1])
        test_pieni_vastaa_moottoria(sys.argv[1])
    print(f"\n{virheita} virhettä")
    sys.exit(1 if virheita else 0)
