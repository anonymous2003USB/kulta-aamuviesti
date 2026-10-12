"""Clauden kultakauppojen istuntotyökalu (koottu tiedostoista moottori.py, ratkaise.py ja muisti.py).
Käyttö:
  python3 istunto.py ratkaise DATAKANSIO DBKANSIO ULOSKANSIO "id=versio,id=versio"
  python3 istunto.py tarkista '<kauppa json>' '<tila json>'
  python3 istunto.py muisti DBKANSIO [YYYY-MM-DD]
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd


TZ = "Europe/Helsinki"
ETAISYYS_ALKAEN = "2026-10-12"
MAX_KAUPPOJA = 6
MAX_TAPPIOITA = 3
MIN_KAUPPOJA = 2


def julkaisun_lahella(nyt, julkaisut, ennen=15, jalkeen=15):
    """Palauttaa julkaisun kellonajan, jos nyt on 15 min ennen – 15 min jälkeen siitä, muuten None."""
    for j in julkaisut:
        tj = pd.Timestamp(f"{nyt:%Y-%m-%d} {j}")
        if tj - pd.Timedelta(minutes=ennen) <= nyt <= tj + pd.Timedelta(minutes=jalkeen):
            return j
    return None


class Hinnat:
    def __init__(self, bid_polku, ask_polku):
        def lue(p):
            d = pd.read_csv(p)
            d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
            return d.set_index("timestamp")[["open", "high", "low", "close"]].astype(float)
        b, a = lue(bid_polku), lue(ask_polku)
        m = b.join(a, how="inner", lsuffix="_b", rsuffix="_a").sort_index()
        m = m[~m.index.duplicated()]
        self.t = m.index
        self.tn = m.index.values
        for k in ("open", "high", "low", "close"):
            setattr(self, "b" + k[0], m[k + "_b"].values)
            setattr(self, "a" + k[0], m[k + "_a"].values)

    def i(self, aika):
        return int(np.searchsorted(self.tn, np.datetime64(aika.tz_convert("UTC").tz_localize(None)), side="left"))


def aikaraja(tf, uusi=False):
    """Vanhat kaupat (ennen 12.10.2026): seuraava klo 23.00. Uudet: klo 23.55 samana päivänä, ennen kullan
    päivittäistä taukoa (00.00 Suomen aikaa), koska herätyksiä on myös klo 21 ja 23."""
    h = tf.tz_convert(TZ)
    raja = h.normalize() + (pd.Timedelta(hours=23, minutes=55) if uusi else pd.Timedelta(hours=23))
    if h >= raja:
        raja = raja + pd.Timedelta(days=1)
    return raja


def osumat(H, jf, je, u, taso, kumpi):
    if je <= jf:
        return None
    if kumpi == "stop":
        x = (H.bl[jf:je] <= taso) if u == 1 else (H.ah[jf:je] >= taso)
    else:
        x = (H.bh[jf:je] >= taso) if u == 1 else (H.al[jf:je] <= taso)
        x[0] = False
    return jf + int(x.argmax()) if x.any() else None


def stop_hinta(H, j, jf, u, taso):
    if j == jf:
        return taso
    return min(taso, H.bo[j]) if u == 1 else max(taso, H.ao[j])


def kauppa(H, jf, je, u, f, sl, tp):
    """Palauttaa (tulos $/oz, syy, exit-indeksi)."""
    s = osumat(H, jf, je, u, sl, "stop")
    k = osumat(H, jf, je, u, tp, "tp")
    if s is not None and (k is None or s <= k):
        return u * (stop_hinta(H, s, jf, u, sl) - f), "SL", s
    if k is not None:
        return u * (tp - f), "TP", k
    return u * ((H.bc[je - 1] if u == 1 else H.ac[je - 1]) - f), "aika", je - 1


def _aika(x, avain_utc, avain_hki):
    if x.get(avain_utc):
        return pd.Timestamp(x[avain_utc]).tz_convert("UTC")
    if x.get(avain_hki):
        return pd.Timestamp(x[avain_hki], tz=TZ).tz_convert("UTC")
    return None


def _iso(t):
    return t.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def ratkaise_kauppa(H, x):
    """x = päiväkirjan kauppa (dict). Palauttaa dictin, jossa tila: suljettu / peruttu / auki / virheellinen."""
    u = 1 if x["suunta"] == "osto" else -1
    tyyppi = x.get("tyyppi", "markkina")
    uusi = x.get("pvm", "") >= ETAISYYS_ALKAEN
    t0 = pd.Timestamp(x["aika_utc"]).tz_convert("UTC").ceil("min")
    e, sl, tp = float(x["entry"]), float(x["sl"]), float(x["tp"])
    loppu = H.t[-1]
    j0 = H.i(t0)
    if j0 >= len(H.t):
        return dict(tila="auki", huom="ei vielä dataa kirjaushetken jälkeen")

    if tyyppi == "limit":
        t_end = _aika(x, "voimassa_utc", "voimassa_hki") or aikaraja(t0, uusi).tz_convert("UTC")
        j1 = H.i(t_end)
        jf = f = None
        for j in range(j0, min(j1, len(H.t))):
            if u == 1:
                if H.ao[j] <= e:
                    if H.bo[j] <= sl:
                        return dict(tila="peruttu", huom="hinta avautui SL:n taakse ennen täyttöä")
                    jf, f = j, float(H.ao[j])
                elif H.al[j] <= e:
                    jf, f = j, e
                elif H.bh[j] >= tp:
                    return dict(tila="peruttu", huom="TP-taso saavutettiin ennen täyttöä",
                                peruttu_utc=_iso(H.t[j]))
            else:
                if H.bo[j] >= e:
                    if H.ao[j] >= sl:
                        return dict(tila="peruttu", huom="hinta avautui SL:n taakse ennen täyttöä")
                    jf, f = j, float(H.bo[j])
                elif H.bh[j] >= e:
                    jf, f = j, e
                elif H.al[j] <= tp:
                    return dict(tila="peruttu", huom="TP-taso saavutettiin ennen täyttöä",
                                peruttu_utc=_iso(H.t[j]))
            if jf is not None:
                break
        if jf is None:
            if t_end > loppu:
                return dict(tila="auki", huom="odottaa täyttöä")
            return dict(tila="peruttu", huom="ei täyttynyt voimassaoloaikana", peruttu_utc=_iso(t_end))
    else:
        jf = j0
        if (H.t[jf] - t0) > pd.Timedelta(minutes=10):
            huom_tauko = f"markkina kiinni kirjaushetkellä, täyttö {H.t[jf].tz_convert(TZ):%H:%M}"
        else:
            huom_tauko = ""
        if x.get("lahella_julkaisua"):
            f = float(H.ah[jf] if u == 1 else H.bl[jf])
        else:
            f = float(H.ao[jf] if u == 1 else H.bo[jf])
        if x.get("pvm", "") >= ETAISYYS_ALKAEN:
            sl, tp = f - u * abs(e - sl), f + u * abs(tp - e)
        if (u == 1 and (f <= sl or f >= tp)) or (u == -1 and (f >= sl or f <= tp)):
            return dict(tila="virheellinen", taytto=round(f, 2), huom="markkinahinta oli jo SL:n tai TP:n takana")

    raja = aikaraja(H.t[jf], uusi)
    je = min(H.i(raja), len(H.t))
    tulos, syy, jx = kauppa(H, jf, je, u, f, sl, tp)
    if syy == "aika" and raja > loppu:
        return dict(tila="auki", huom="täyttynyt, data loppuu ennen aikarajaa", taytto=round(f, 2),
                    taytto_utc=_iso(H.t[jf]))
    exit_hinta = f + u * tulos
    # vertailu: sama hetki ja samat etäisyydet vastakkaiseen suuntaan (vain raporttiin)
    fv = float(H.bo[jf] if u == 1 else H.ao[jf])
    slv, tpv = fv + u * abs(f - sl), fv - u * abs(tp - f)
    vast, _, _ = kauppa(H, jf, je, -u, fv, slv, tpv)
    lotit = float(x.get("lotit", 0.01))
    out = dict(tila="suljettu", syy={"TP": "tp", "SL": "sl", "aika": "kasin"}[syy], taytto=round(f, 2),
               taytto_utc=_iso(H.t[jf]), sl_kaytetty=round(sl, 2), tp_kaytetty=round(tp, 2),
               exit=round(exit_hinta, 2), exit_utc=_iso(H.t[jx]), tulos_oz=round(tulos, 3),
               tulos_usd=round(tulos * lotit * 100, 2), vastakkainen_usd=round(vast * lotit * 100, 2))
    if tyyppi != "limit" and huom_tauko:
        out["huom"] = huom_tauko
    return out


def tarkista_kauppa(k, tila):
    """Palauttaa listan virheistä. Tyhjä lista = kaupan saa kirjata.
    k: suunta, tyyppi (markkina/limit), entry, sl, tp, [voimassa_hki "YYYY-MM-DD HH:MM"]
    tila: bid, ask, datan_ika_min, nyt_hki "YYYY-MM-DD HH:MM", kauppoja_tanaan, tappioita_tanaan, julkaisut ["HH:MM"]
    Rajat: enintään 6 kauppaa päivässä, ei uusia kauppoja 3 tappion jälkeen."""
    v = []
    if k.get("suunta") not in ("osto", "myynti"):
        return ["suunta pitää olla osto tai myynti"]
    tyyppi = k.get("tyyppi", "markkina")
    if tyyppi not in ("markkina", "limit"):
        return ["tyyppi pitää olla markkina tai limit"]
    u = 1 if k["suunta"] == "osto" else -1
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
    if tila.get("kauppoja_tanaan", 0) >= MAX_KAUPPOJA:
        v.append(f"päivän {MAX_KAUPPOJA} kauppaa on jo tehty")
    if tila.get("tappioita_tanaan", 0) >= MAX_TAPPIOITA:
        v.append(f"{MAX_TAPPIOITA} tappiota tänään: ei uusia kauppoja")
    nyt = pd.Timestamp(tila["nyt_hki"])
    if not (nyt.hour >= 6 and (nyt.hour < 23 or (nyt.hour == 23 and nyt.minute <= 30))):
        v.append("kauppoja vain klo 6.00–23.30 (klo 1–6 vältetään, kaupat suljetaan klo 23.55)")
    bid, ask = float(tila["bid"]), float(tila["ask"])
    if tyyppi == "markkina":
        markkina = ask if u == 1 else bid
        if abs(e - markkina) > 1.0:
            v.append(f"entry {e} ei vastaa markkinahintaa {markkina}")
        lahella = julkaisun_lahella(nyt, tila.get("julkaisut", []))
        if lahella and not k.get("lahella_julkaisua"):
            v.append(f"ison julkaisun ({lahella}) lähellä: lisää kauppaan kenttä \"lahella_julkaisua\": true "
                     "(täyttö lasketaan minuutin huonoimpaan hintaan)")
    else:
        if u == 1 and not e < ask:
            v.append("osto-limitin pitää olla markkinahinnan alapuolella")
        if u == -1 and not e > bid:
            v.append("myynti-limitin pitää olla markkinahinnan yläpuolella")
        if not k.get("voimassa_hki"):
            v.append("limitiltä puuttuu voimassa_hki")
        else:
            loppu = pd.Timestamp(k["voimassa_hki"])
            if not (nyt < loppu <= nyt.normalize() + pd.Timedelta(hours=23, minutes=30)):
                v.append("limitin voimassaolon pitää päättyä tänään viimeistään klo 23.30")
            elif loppu - nyt > pd.Timedelta(hours=4):
                v.append("limitin voimassaolo enintään 4 tuntia")
    return v


# ---- ratkaise ----
HKI = "Europe/Helsinki"


def hki(iso):
    return pd.Timestamp(iso).tz_convert(HKI)


def ratkaise_main(data, dbk, ulos, versiot):
    os.makedirs(ulos, exist_ok=True)
    H = Hinnat(f"{data}/m1_bid.csv", f"{data}/m1_ask.csv")
    nyt = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    writes, rivit = [], []
    for f in sorted(glob.glob(f"{dbk}/**/*.json", recursive=True)):
        doc_id = os.path.basename(f)[:-5]
        x = json.load(open(f))
        x = x.get("data", x)
        if x.get("tekija") != "claude" or x.get("tila") != "auki":
            continue
        r = ratkaise_kauppa(H, x)
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


# ---- muisti ----
SMC_ALKAA = "2026-10-12"
MALLIT = {"pyyhkaisy_choch": "Likviditeetin pyyhkäisy + CHoCH", "vyohyke_retesti": "Paluu vyöhykkeelle trendin suuntaan",
          "fvg_jatko": "Paluu FVG:hen BOS:n jälkeen", "muu": "Muu"}


def lue_kaupat(dbk):
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


def muisti_main(dbk, tanaan=None):
    k = lue_kaupat(dbk)
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
    pak = [x for x in smc if x.get("pakotettu")]
    if pak:
        print(f"    Pakotetut (minimi 2/pv): {tilasto(pak)}")
        print(f"    Ei pakotetut:            {tilasto([x for x in smc if not x.get('pakotettu')])}")
    perutut = [x for x in smc if x.get("tila") in ("peruttu", "virheellinen")]
    if perutut:
        print(f"  Peruttuja/virheellisiä toimeksiantoja: {len(perutut)}")
    print("\nVIIMEISET 20 KAUPPAA (vanhin ensin)")
    for x in k[-20:]:
        tulos = f"{x['tulosValittaja']:+.2f} $ ({R(x):+.1f} R, {x.get('syy', '')})" \
            if x.get("tila") == "suljettu" and isinstance(x.get("tulosValittaja"), (int, float)) else x.get("tila", "")
        print(f"  {x.get('pvm')} {x.get('klo')} {x.get('suunta'):6s} {x.get('tyyppi', 'markkina'):8s} "
              f"{x.get('malli', '-'):16s} {tulos}{' PAKOTETTU' if x.get('pakotettu') else ''}"
              f"{' (julkaisu)' if x.get('lahella_julkaisua') else ''}")
        if x.get("setup"):
            print(f"      setup: {x['setup']}")
        if x.get("opetus"):
            print(f"      opetus: {x['opetus']}")
    if tanaan:
        t = [x for x in k if x.get("pvm") == tanaan and x.get("tila") not in ("virheellinen", "peruttu")]
        tappiot = [x for x in t if x.get("tila") == "suljettu" and x.get("tulosValittaja", 0) < 0]
        auki = [x for x in t if x.get("tila") == "auki"]
        print(f"\nTÄNÄÄN {tanaan}: kauppoja {len(t)} (vähintään 2, enintään 6), tappioita {len(tappiot)} "
              f"(3 tappion jälkeen ei uusia), auki/odottaa {len(auki)}")
        for x in auki:
            print(f"  auki: {x['_id']} {x['suunta']} {x.get('tyyppi', 'markkina')} entry {x['entry']} SL {x['sl']} TP {x['tp']}"
                  f"{' voimassa ' + x['voimassa_hki'] if x.get('voimassa_hki') else ''}")
    ilman = [x["_id"] for x in k if x.get("tila") == "suljettu" and not x.get("opetus") and x.get("pvm", "") >= SMC_ALKAA]
    if ilman:
        print(f"\nOPETUS PUUTTUU: {', '.join(ilman)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "ratkaise":
        v = {}
        for pari in (a[4] if len(a) > 4 else "").split(","):
            if "=" in pari:
                d_id, n = pari.strip().split("=")
                v[d_id.strip()] = int(n)
        ratkaise_main(a[1], a[2], a[3], v)
    elif a and a[0] == "tarkista":
        virheet = tarkista_kauppa(json.loads(a[1]), json.loads(a[2]))
        print(json.dumps(virheet, ensure_ascii=False))
        sys.exit(1 if virheet else 0)
    elif a and a[0] == "muisti":
        muisti_main(a[1], a[2] if len(a) > 2 else None)
    else:
        print(__doc__)
        sys.exit(2)
