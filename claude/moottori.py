"""Kauppojen ratkaisu minuuttidatalla ja kauppojen tarkistus ennen kirjausta.

Säännöt (samat kuin kaikissa aiemmissa testeissä):
- Markkinakauppa täyttyy kirjausminuutin avaushintaan (osto ask, myynti bid). 12.10.2026 alkaen SL ja TP ovat
  etäisyyksiä kirjatusta entrystä, jolloin vanhentunut hinta ei voi siirtää tasoja.
- Limit-kauppa täyttyy, kun hinta koskettaa tasoa (osto: ask low <= entry, myynti: bid high >= entry) ennen
  voimassaolon loppua. Jos hinta avautuu tason yli, täyttö tapahtuu avaushintaan. Jos TP-taso saavutetaan ennen
  täyttöä, toimeksianto perutaan. Täyttymätön toimeksianto perutaan voimassaolon päättyessä.
- SL tai TP, kumpi ensin. Sama minuutti -> SL. TP ei voi osua täyttöminuutissa.
- Aikaraja: seuraava klo 23.00 Suomen aikaa, jolloin kauppa suljetaan markkinahintaan.
"""
import numpy as np
import pandas as pd

TZ = "Europe/Helsinki"
ETAISYYS_ALKAEN = "2026-10-12"


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


def aikaraja(tf):
    h = tf.tz_convert(TZ)
    raja = h.normalize() + pd.Timedelta(hours=23)
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
    t0 = pd.Timestamp(x["aika_utc"]).tz_convert("UTC").ceil("min")
    e, sl, tp = float(x["entry"]), float(x["sl"]), float(x["tp"])
    loppu = H.t[-1]
    j0 = H.i(t0)
    if j0 >= len(H.t):
        return dict(tila="auki", huom="ei vielä dataa kirjaushetken jälkeen")

    if tyyppi == "limit":
        t_end = _aika(x, "voimassa_utc", "voimassa_hki") or aikaraja(t0).tz_convert("UTC")
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
        f = float(H.ao[jf] if u == 1 else H.bo[jf])
        if x.get("pvm", "") >= ETAISYYS_ALKAEN:
            sl, tp = f - u * abs(e - sl), f + u * abs(tp - e)
        if (u == 1 and (f <= sl or f >= tp)) or (u == -1 and (f >= sl or f <= tp)):
            return dict(tila="virheellinen", taytto=round(f, 2), huom="markkinahinta oli jo SL:n tai TP:n takana")

    raja = aikaraja(H.t[jf])
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
    tila: bid, ask, datan_ika_min, nyt_hki "YYYY-MM-DD HH:MM", kauppoja_tanaan, tappioita_tanaan, julkaisut ["HH:MM"]"""
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
    if tila.get("kauppoja_tanaan", 0) >= 3:
        v.append("päivän 3 kauppaa on jo tehty")
    if tila.get("tappioita_tanaan", 0) >= 2:
        v.append("2 tappiota tänään: ei uusia kauppoja")
    nyt = pd.Timestamp(tila["nyt_hki"])
    if not (nyt.hour >= 9 and (nyt.hour < 21 or (nyt.hour == 21 and nyt.minute == 0))):
        v.append("kauppoja vain klo 9.00–21.00")
    bid, ask = float(tila["bid"]), float(tila["ask"])
    if tyyppi == "markkina":
        markkina = ask if u == 1 else bid
        if abs(e - markkina) > 1.0:
            v.append(f"entry {e} ei vastaa markkinahintaa {markkina}")
        for j in tila.get("julkaisut", []):
            tj = pd.Timestamp(f"{nyt:%Y-%m-%d} {j}")
            if tj - pd.Timedelta(minutes=30) <= nyt <= tj + pd.Timedelta(minutes=15):
                v.append(f"ison julkaisun ({j}) lähellä ei avata markkinakauppaa")
    else:
        if u == 1 and not e < ask:
            v.append("osto-limitin pitää olla markkinahinnan alapuolella")
        if u == -1 and not e > bid:
            v.append("myynti-limitin pitää olla markkinahinnan yläpuolella")
        if not k.get("voimassa_hki"):
            v.append("limitiltä puuttuu voimassa_hki")
        else:
            loppu = pd.Timestamp(k["voimassa_hki"])
            if not (nyt < loppu <= nyt.normalize() + pd.Timedelta(hours=21)):
                v.append("limitin voimassaolon pitää päättyä tänään viimeistään klo 21.00")
    return v
