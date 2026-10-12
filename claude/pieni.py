"""Clauden kaupat: tarkistus ja ratkaisu (tiivis, sama logiikka kuin moottori.py).
python3 pieni.py tarkista '<kauppa json>' '<tila json>'
python3 pieni.py ratkaise DATAKANSIO KAUPAT   (KAUPAT = query out_dir -kansio tai JSON-lista, jossa "id")
python3 pieni.py tanaan KAUPAT YYYY-MM-DD
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

TZ = "Europe/Helsinki"
UUSI_ALKAEN = "2026-10-12"


class Hinnat:
    def __init__(self, bid_polku, ask_polku):
        def lue(p):
            d = pd.read_csv(p)
            d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
            return d.set_index("timestamp")[["open", "high", "low", "close"]].astype(float)
        m = lue(bid_polku).join(lue(ask_polku), how="inner", lsuffix="_b", rsuffix="_a").sort_index()
        m = m[~m.index.duplicated()]
        self.t, self.tn = m.index, m.index.values
        for k in ("open", "high", "low", "close"):
            setattr(self, "b" + k[0], m[k + "_b"].values)
            setattr(self, "a" + k[0], m[k + "_a"].values)

    def i(self, aika):
        return int(np.searchsorted(self.tn, np.datetime64(aika.tz_convert("UTC").tz_localize(None)), side="left"))


def aikaraja(tf, uusi=False):
    h = tf.tz_convert(TZ)
    raja = h.normalize() + (pd.Timedelta(hours=23, minutes=55) if uusi else pd.Timedelta(hours=23))
    return raja + pd.Timedelta(days=1) if h >= raja else raja


def osumat(H, jf, je, u, taso, kumpi):
    if je <= jf:
        return None
    if kumpi == "stop":
        x = (H.bl[jf:je] <= taso) if u == 1 else (H.ah[jf:je] >= taso)
    else:
        x = (H.bh[jf:je] >= taso) if u == 1 else (H.al[jf:je] <= taso)
        x[0] = False
    return jf + int(x.argmax()) if x.any() else None


def kauppa(H, jf, je, u, f, sl, tp):
    s, k = osumat(H, jf, je, u, sl, "stop"), osumat(H, jf, je, u, tp, "tp")
    if s is not None and (k is None or s <= k):
        hinta = sl if s == jf else (min(sl, H.bo[s]) if u == 1 else max(sl, H.ao[s]))
        return u * (hinta - f), "SL", s
    if k is not None:
        return u * (tp - f), "TP", k
    return u * ((H.bc[je - 1] if u == 1 else H.ac[je - 1]) - f), "aika", je - 1


def iso(t):
    return t.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def ratkaise_kauppa(H, x):
    u = 1 if x["suunta"] == "osto" else -1
    tyyppi, uusi = x.get("tyyppi", "markkina"), x.get("pvm", "") >= UUSI_ALKAEN
    t0 = pd.Timestamp(x["aika_utc"]).tz_convert("UTC").ceil("min")
    e, sl, tp = float(x["entry"]), float(x["sl"]), float(x["tp"])
    loppu, j0 = H.t[-1], H.i(t0)
    if j0 >= len(H.t):
        return dict(tila="auki", huom="ei vielä dataa kirjaushetken jälkeen")
    if tyyppi == "limit":
        if x.get("voimassa_utc"):
            t_end = pd.Timestamp(x["voimassa_utc"]).tz_convert("UTC")
        elif x.get("voimassa_hki"):
            t_end = pd.Timestamp(x["voimassa_hki"], tz=TZ).tz_convert("UTC")
        else:
            t_end = aikaraja(t0, uusi).tz_convert("UTC")
        jf = f = None
        for j in range(j0, min(H.i(t_end), len(H.t))):
            if u == 1:
                if H.ao[j] <= e:
                    if H.bo[j] <= sl:
                        return dict(tila="peruttu", huom="hinta avautui SL:n taakse ennen täyttöä")
                    jf, f = j, float(H.ao[j])
                elif H.al[j] <= e:
                    jf, f = j, e
                elif H.bh[j] >= tp:
                    return dict(tila="peruttu", huom="TP-taso saavutettiin ennen täyttöä", peruttu_utc=iso(H.t[j]))
            else:
                if H.bo[j] >= e:
                    if H.ao[j] >= sl:
                        return dict(tila="peruttu", huom="hinta avautui SL:n taakse ennen täyttöä")
                    jf, f = j, float(H.bo[j])
                elif H.bh[j] >= e:
                    jf, f = j, e
                elif H.al[j] <= tp:
                    return dict(tila="peruttu", huom="TP-taso saavutettiin ennen täyttöä", peruttu_utc=iso(H.t[j]))
            if jf is not None:
                break
        if jf is None:
            if t_end > loppu:
                return dict(tila="auki", huom="odottaa täyttöä")
            return dict(tila="peruttu", huom="ei täyttynyt voimassaoloaikana", peruttu_utc=iso(t_end))
    else:
        jf = j0
        if x.get("lahella_julkaisua"):
            f = float(H.ah[jf] if u == 1 else H.bl[jf])
        else:
            f = float(H.ao[jf] if u == 1 else H.bo[jf])
        if uusi:
            sl, tp = f - u * abs(e - sl), f + u * abs(tp - e)
        if (u == 1 and (f <= sl or f >= tp)) or (u == -1 and (f >= sl or f <= tp)):
            return dict(tila="virheellinen", taytto=round(f, 2), huom="markkinahinta oli jo SL:n tai TP:n takana")
    raja = aikaraja(H.t[jf], uusi)
    je = min(H.i(raja), len(H.t))
    tulos, syy, jx = kauppa(H, jf, je, u, f, sl, tp)
    if syy == "aika" and raja > loppu:
        return dict(tila="auki", huom="täyttynyt, data loppuu ennen aikarajaa", taytto=round(f, 2), taytto_utc=iso(H.t[jf]))
    lotit = float(x.get("lotit", 0.01))
    return dict(tila="suljettu", syy={"TP": "tp", "SL": "sl", "aika": "kasin"}[syy], taytto=round(f, 2),
                taytto_utc=iso(H.t[jf]), exit=round(f + u * tulos, 2), exit_utc=iso(H.t[jx]),
                tulos_oz=round(float(tulos), 3), tulos_usd=round(float(tulos) * lotit * 100, 2))


def tarkista_kauppa(k, tila):
    v = []
    if k.get("suunta") not in ("osto", "myynti") or k.get("tyyppi", "markkina") not in ("markkina", "limit"):
        return ["suunta pitää olla osto/myynti ja tyyppi markkina/limit"]
    u, tyyppi = (1 if k["suunta"] == "osto" else -1), k.get("tyyppi", "markkina")
    e, sl, tp = float(k["entry"]), float(k["sl"]), float(k["tp"])
    if not u * (e - sl) > 0:
        v.append("SL on väärällä puolella entryä")
    if not u * (tp - e) > 0:
        v.append("TP on väärällä puolella entryä")
    riski = abs(e - sl)
    if not 5 <= riski <= 30:
        v.append(f"SL:n etäisyys {riski:.1f} $ (sallittu 5–30 $)")
    if riski > 0 and abs(tp - e) / riski < 2:
        v.append(f"RR {abs(tp - e) / riski:.2f} (vähintään 2)")
    if tila.get("datan_ika_min") is None or tila["datan_ika_min"] > 15:
        v.append(f"data liian vanha ({tila.get('datan_ika_min')} min)")
    if tila.get("kauppoja_tanaan", 0) >= 6:
        v.append("päivän 6 kauppaa on jo tehty")
    if tila.get("tappioita_tanaan", 0) >= 3:
        v.append("3 tappiota tänään: ei uusia kauppoja")
    nyt = pd.Timestamp(tila["nyt_hki"])
    if not (nyt.hour >= 6 and (nyt.hour < 23 or (nyt.hour == 23 and nyt.minute <= 30))):
        v.append("kauppoja vain klo 6.00–23.30")
    bid, ask = float(tila["bid"]), float(tila["ask"])
    if tyyppi == "markkina":
        markkina = ask if u == 1 else bid
        if abs(e - markkina) > 1.0:
            v.append(f"entry {e} ei vastaa markkinahintaa {markkina}")
        for j in tila.get("julkaisut", []):
            tj = pd.Timestamp(f"{nyt:%Y-%m-%d} {j}")
            if tj - pd.Timedelta(minutes=15) <= nyt <= tj + pd.Timedelta(minutes=15) and not k.get("lahella_julkaisua"):
                v.append(f"julkaisun ({j}) lähellä: lisää kenttä \"lahella_julkaisua\": true")
    else:
        if (u == 1 and not e < ask) or (u == -1 and not e > bid):
            v.append("osto-limitin pitää olla markkinahinnan alla ja myynti-limitin sen yllä")
        if not k.get("voimassa_hki"):
            v.append("limitiltä puuttuu voimassa_hki")
        else:
            loppu = pd.Timestamp(k["voimassa_hki"])
            if not (nyt < loppu <= nyt.normalize() + pd.Timedelta(hours=23, minutes=30)):
                v.append("limitin voimassaolon pitää päättyä tänään viimeistään klo 23.30")
            elif loppu - nyt > pd.Timedelta(hours=4):
                v.append("limitin voimassaolo enintään 4 tuntia")
    return v


def paivitys(x, r, nyt):
    if r["tila"] == "suljettu":
        ex = pd.Timestamp(r["exit_utc"]).tz_convert(TZ)
        return dict(tila="suljettu", exit=r["exit"], syy=r["syy"], taytto=r["taytto"], tulosValittaja=r["tulos_usd"],
                    suljettuPvm=ex.strftime("%Y-%m-%d"), suljettu=ex.isoformat(timespec="minutes"),
                    taytto_utc=r["taytto_utc"], exit_utc=r["exit_utc"], ratkaistu=f"minuuttidata {nyt}")
    if r["tila"] in ("peruttu", "virheellinen"):
        d = dict(tila=r["tila"], huom=r.get("huom", ""), ratkaistu=f"minuuttidata {nyt}")
        if "taytto" in r:
            d["taytto"] = r["taytto"]
        return d
    if r.get("taytto") is not None and x.get("taytto") is None:
        return dict(taytto=r["taytto"], taytto_utc=r["taytto_utc"])
    return None


def lue_kaupat(polku):
    if os.path.isdir(polku):
        out = []
        for f in sorted(glob.glob(f"{polku}/**/*.json", recursive=True)):
            x = json.load(open(f))
            x = dict(x.get("data", x))
            x.setdefault("id", os.path.basename(f)[:-5])
            out.append(x)
        return out
    return json.load(open(polku))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["tarkista"]:
        print(json.dumps(tarkista_kauppa(json.loads(a[1]), json.loads(a[2])), ensure_ascii=False))
    elif a[:1] == ["ratkaise"]:
        H = Hinnat(f"{a[1]}/m1_bid.csv", f"{a[1]}/m1_ask.csv")
        nyt = pd.Timestamp.now(tz=TZ).strftime("%Y-%m-%d %H:%M")
        tulos = []
        for x in lue_kaupat(a[2]):
            if x.get("tekija", "claude") == "claude" and x.get("tila") == "auki":
                r = ratkaise_kauppa(H, x)
                p = paivitys(x, r, nyt)
                tulos.append(dict(id=x["id"], tila=r["tila"], tulos_usd=r.get("tulos_usd"), paivitys=p))
        print(json.dumps(tulos, ensure_ascii=False, indent=1))
    elif a[:1] == ["tanaan"]:
        k = [x for x in lue_kaupat(a[1]) if x.get("pvm") == a[2] and x.get("tila") not in ("peruttu", "virheellinen")]
        tappiot = [x for x in k if x.get("tila") == "suljettu" and float(x.get("tulosValittaja", 0)) < 0]
        print(json.dumps(dict(kauppoja_tanaan=len(k), tappioita_tanaan=len(tappiot),
                              auki=[x["id"] for x in k if x.get("tila") == "auki"]), ensure_ascii=False))
    else:
        print(__doc__)
