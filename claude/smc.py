"""SMC-, supply/demand- ja price action -analyysi kullalle (XAU/USD) Dukascopyn kynttilöistä.

Käyttö:
  python -I smc.py DATAKANSIO ULOSKANSIO [--aika "2026-10-07 15:30"]
DATAKANSIO: m1_bid.csv, m1_ask.csv, h1_bid.csv (hae_hinnat.py)
--aika: Suomen aika. Analyysi käyttää vain sitä ennen sulkeutuneita kynttilöitä (testaus ilman tulevaa dataa).
Tuottaa ULOSKANSIOON: analyysi.txt, analyysi.json, h1.png, m15.png.
Jos datan tarkistus löytää virheen, tulostaa VIRHE-rivit ja palauttaa koodin 2. Silloin ei saa käydä kauppaa.

Määritelmät (kiinteät, jotta jokainen analyysi tehdään samalla tavalla):
- Kynttilät: H4 ja D alkavat New Yorkin klo 17.00 sulun mukaan; Aasian alue = Suomen aikaa 03.00–09.00.
- Swing: kynttilän high (low) on korkein (matalin) N kynttilää molemmin puolin; tiedossa vasta N kynttilän jälkeen.
- BOS/CHoCH: sulkuhinta ylittää viimeisimmän swing highin (alittaa swing lown). Trendin suuntaan BOS, vastaan CHoCH.
- Kysyntä/tarjonta (order block): rakennemurtoa edeltäneen liikkeen alkupisteen viimeinen vastakkaisvärinen kynttilä.
  Mitätöity, kun hinta sulkeutuu vyöhykkeen läpi. "Koskematon" = hinta ei ole palannut vyöhykkeelle.
- FVG: kolmen kynttilän aukko (1. kynttilän high < 3. kynttilän low tai päinvastoin), vähintään 0,1 × ATR.
- Premium/discount: hinnan sijainti H4-alueella (viimeisin swing low – swing high); alle 50 % = discount.
"""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HKI = "Europe/Helsinki"
NY = "America/New_York"
SWING_N = {"D": 2, "H4": 2, "H1": 3, "M15": 3, "M5": 3}


# ---------------------------------------------------------------- data

def lue(p):
    d = pd.read_csv(p)
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    d = d.set_index("timestamp").sort_index()
    return d[["open", "high", "low", "close"]].astype(float)


def kynttilat(m1, saanto, tz="UTC", offset=None):
    x = m1.tz_convert(tz)
    r = x.resample(saanto, offset=offset, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return r.tz_convert("UTC")


def paivat(h1):
    """NY-kaupankäyntipäivät: klo 17.00 (New York) – 17.00. Indeksi = päivän alkuhetki UTC."""
    paikallinen = h1.index.tz_convert(NY).tz_localize(None)
    avain = (paikallinen + pd.Timedelta(hours=7)).floor("D")
    d = h1.groupby(avain).agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    alku = (d.index - pd.Timedelta(hours=7)).tz_localize(NY, ambiguous="NaT", nonexistent="shift_forward")
    d.index = alku.tz_convert("UTC")
    return d


def paivan_alku(t):
    """Meneillään olevan NY-päivän alkuhetki (klo 17.00 New York) UTC-aikana."""
    p = t.tz_convert(NY).tz_localize(None)
    alku = (p + pd.Timedelta(hours=7)).floor("D") - pd.Timedelta(hours=7)
    return alku.tz_localize(NY).tz_convert("UTC")


def suljetut(k, kesto, t):
    """Vain kynttilät, jotka ovat sulkeutuneet hetkeen t mennessä."""
    return k[k.index + kesto <= t]


def atr(k, n=14):
    pc = k.close.shift()
    tr = pd.concat([k.high - k.low, (k.high - pc).abs(), (k.low - pc).abs()], axis=1).max(axis=1)
    return float(tr.tail(n).mean())


# ---------------------------------------------------------------- rakenne

def swingit(k, n):
    h, l = k.high.values, k.low.values
    out = []
    for i in range(n, len(k) - n):
        if h[i] > h[i - n:i].max() and h[i] >= h[i + 1:i + n + 1].max():
            out.append((i, "H", float(h[i])))
        if l[i] < l[i - n:i].min() and l[i] <= l[i + 1:i + n + 1].min():
            out.append((i, "L", float(l[i])))
    return out


def rakenne(k, n):
    """Palauttaa (trendi, tapahtumat, swingit). trendi 1 nousu, -1 lasku, 0 ei tiedossa."""
    sw = swingit(k, n)
    jono = sorted(sw, key=lambda s: s[0])
    c = k.close.values
    trendi, tap, p = 0, [], 0
    vH = vL = None
    for j in range(len(k)):
        while p < len(jono) and jono[p][0] + n <= j:
            i, t, lv = jono[p]
            p += 1
            if t == "H":
                vH = [i, lv, False]
            else:
                vL = [i, lv, False]
        if vH and not vH[2] and c[j] > vH[1]:
            tap.append(dict(j=j, suunta=1, tyyppi="BOS" if trendi >= 0 else "CHoCH", taso=vH[1], swing_i=vH[0]))
            trendi, vH[2] = 1, True
        if vL and not vL[2] and c[j] < vL[1]:
            tap.append(dict(j=j, suunta=-1, tyyppi="BOS" if trendi <= 0 else "CHoCH", taso=vL[1], swing_i=vL[0]))
            trendi, vL[2] = -1, True
    return trendi, tap, sw


def fvgt(k, a):
    h, l = k.high.values, k.low.values
    out = []
    for i in range(1, len(k) - 1):
        if l[i + 1] - h[i - 1] >= 0.1 * a:
            out.append(dict(i=i + 1, suunta=1, ala=float(h[i - 1]), yla=float(l[i + 1])))
        if l[i - 1] - h[i + 1] >= 0.1 * a:
            out.append(dict(i=i + 1, suunta=-1, ala=float(h[i + 1]), yla=float(l[i - 1])))
    for f in out:  # täyttyminen myöhemmillä kynttilöillä
        jalk = k.iloc[f["i"] + 1:]
        if f["suunta"] == 1:
            f["taytetty"] = bool((jalk.low <= f["ala"]).any())
            f["osittain"] = bool((jalk.low < f["yla"]).any())
        else:
            f["taytetty"] = bool((jalk.high >= f["yla"]).any())
            f["osittain"] = bool((jalk.high > f["ala"]).any())
    return out


def vyohykkeet(k, tap, fv, a):
    """Order block / kysyntä-tarjonta jokaisesta rakennemurrosta."""
    o, c, h, l = k.open.values, k.close.values, k.high.values, k.low.values
    out = []
    for e in tap:
        j, s, u = e["j"], e["swing_i"], e["suunta"]
        if j <= s:
            continue
        m = s + int(np.argmin(l[s:j + 1])) if u == 1 else s + int(np.argmax(h[s:j + 1]))
        ob = m
        for b in range(m, max(m - 4, -1), -1):
            if (u == 1 and c[b] < o[b]) or (u == -1 and c[b] > o[b]):
                ob = b
                break
        ala, yla = float(l[ob]), float(h[ob])
        siirtyma = any(f["suunta"] == u and m < f["i"] <= j + 1 for f in fv) or \
            bool(((h[m:j + 1] - l[m:j + 1]) >= 1.5 * a).any())
        jalk = k.iloc[j + 1:]
        if u == 1:
            kosketus = jalk.low <= yla
            mitatoity = bool((jalk.close < ala).any())
        else:
            kosketus = jalk.high >= ala
            mitatoity = bool((jalk.close > yla).any())
        kaynnit = int((kosketus.astype(int).diff().fillna(kosketus.astype(int)) == 1).sum())
        out.append(dict(i=ob, j=j, suunta=u, ala=ala, yla=yla, murto=e["tyyppi"], siirtyma=siirtyma,
                        kaynnit=kaynnit, mitatoity=mitatoity))
    # päällekkäiset samansuuntaiset: pidetään uusin
    uniq = []
    for z in sorted(out, key=lambda z: -z["j"]):
        if not any(q["suunta"] == z["suunta"] and q["ala"] <= z["yla"] and z["ala"] <= q["yla"] for q in uniq):
            uniq.append(z)
    return sorted(uniq, key=lambda z: z["j"])


# ---------------------------------------------------------------- likviditeetti

def pyyhkaisy(k_jalk, taso, ylos):
    """Onko taso ylitetty (ylos) / alitettu myöhemmin. Palauttaa (aika tai None, sulkiko takaisin)."""
    x = k_jalk.high > taso if ylos else k_jalk.low < taso
    if not x.any():
        return None, False
    t = x.idxmax()
    rivi = k_jalk.loc[t]
    takaisin = bool(rivi.close < taso) if ylos else bool(rivi.close > taso)
    return t, takaisin


def likviditeetti(m1, d1, h1sw, h1, m15, m15sw, t, a_h1):
    out = []
    pv = d1  # sisältää vain sulkeutuneet NY-päivät
    tanaan_alku = paivan_alku(t)
    tanaan = m1[m1.index >= tanaan_alku]
    if len(pv):
        ed = pv.iloc[-1]
        for nimi, taso, ylos in (("PDH (eilisen huippu)", ed.high, True), ("PDL (eilisen pohja)", ed.low, False)):
            out.append(dict(nimi=nimi, taso=float(taso), ylos=ylos, alku=tanaan_alku))
    # viikko alkaa sunnuntaina klo 17.00 New Yorkin aikaa
    p = tanaan_alku.tz_convert(NY).tz_localize(None)
    vk_alku = (p - pd.Timedelta(days=(p.weekday() - 6) % 7)).tz_localize(NY).tz_convert("UTC")
    viikko = pv[(pv.index < vk_alku) & (pv.index >= vk_alku - pd.Timedelta(days=7))]
    if len(viikko):
        out.append(dict(nimi="Ed. viikon huippu", taso=float(viikko.high.max()), ylos=True, alku=vk_alku))
        out.append(dict(nimi="Ed. viikon pohja", taso=float(viikko.low.min()), ylos=False, alku=vk_alku))
    hk = t.tz_convert(HKI)
    a0 = hk.normalize() + pd.Timedelta(hours=3)
    a1 = hk.normalize() + pd.Timedelta(hours=9)
    if hk >= a1:
        asia = m1[(m1.index >= a0.tz_convert("UTC")) & (m1.index < a1.tz_convert("UTC"))]
        if len(asia):
            out.append(dict(nimi="Aasian huippu", taso=float(asia.high.max()), ylos=True, alku=a1.tz_convert("UTC")))
            out.append(dict(nimi="Aasian pohja", taso=float(asia.low.min()), ylos=False, alku=a1.tz_convert("UTC")))
    # tasaiset huiput/pohjat (H1 ja M15), viim. 3 päivää
    tol = 0.1 * a_h1
    for nimi_tf, k, sw in (("H1", h1, h1sw), ("M15", m15, m15sw)):
        raja = t - pd.Timedelta(days=3)
        for tyyppi, ylos in (("H", True), ("L", False)):
            pts = [(k.index[i], lv) for i, tt, lv in sw if tt == tyyppi and k.index[i] >= raja]
            for x in range(len(pts)):
                for y in range(x + 1, len(pts)):
                    if abs(pts[x][1] - pts[y][1]) <= tol:
                        taso = max(pts[x][1], pts[y][1]) if ylos else min(pts[x][1], pts[y][1])
                        nimi = f"Tasaiset {'huiput' if ylos else 'pohjat'} ({nimi_tf})"
                        if not any(abs(o["taso"] - taso) <= tol and o["nimi"] == nimi for o in out):
                            out.append(dict(nimi=nimi, taso=float(taso), ylos=ylos,
                                            alku=pts[y][0] + pd.Timedelta(minutes=60 if nimi_tf == "H1" else 15)))
    for o in out:
        jalk = m1[m1.index >= o["alku"]]
        tp, tak = pyyhkaisy(jalk, o["taso"], o["ylos"])
        o["pyyhkaisty"] = None if tp is None else tp.tz_convert(HKI).strftime("%d.%m. %H:%M")
        o["pyyhkaisty_utc"] = tp
        o["sulki_takaisin"] = tak
    hinta = float(m1.close.iloc[-1])
    perus = [o for o in out if not o["nimi"].startswith("Tasaiset")]
    tas = [o for o in out if o["nimi"].startswith("Tasaiset") and
           (o["pyyhkaisty_utc"] is None or o["pyyhkaisty_utc"] >= t - pd.Timedelta(hours=24))]
    valitut = []
    for ylos in (True, False):
        puoli = [o for o in tas if o["ylos"] == ylos]
        valitut += sorted(puoli, key=lambda o: abs(o["taso"] - hinta))[:3]
    out = perus + valitut
    for o in out:
        o.pop("pyyhkaisty_utc", None)
    return out, tanaan


# ---------------------------------------------------------------- tarkistukset

def tarkista(b, a, h1_duk, nyt=None):
    virheet, huom = [], []
    for nimi, d in (("m1_bid", b), ("m1_ask", a), ("h1_bid", h1_duk)):
        if d.index.duplicated().any():
            virheet.append(f"{nimi}: toistuvia aikaleimoja")
        if d.isna().any().any():
            virheet.append(f"{nimi}: puuttuvia arvoja")
        if not ((d.high >= d[["open", "close"]].max(axis=1) - 1e-9) & (d.low <= d[["open", "close"]].min(axis=1) + 1e-9)).all():
            virheet.append(f"{nimi}: high/low ristiriidassa")
    yht = b.index.intersection(a.index)
    sp = a.loc[yht, "close"] - b.loc[yht, "close"]
    if len(yht) < 0.95 * min(len(a), len(b)):
        virheet.append("bid- ja ask-minuutit eivät täsmää")
    if (sp < -0.01).any() or sp.median() > 2 or sp.max() > 15:
        virheet.append(f"spread outo: mediaani {sp.median():.2f}, max {sp.max():.2f}")
    # Dukascopyn oma H1 vs minuuteista koottu H1: paljastaa aikavyöhyke- ja kohdistusvirheet
    oma = kynttilat(b, "1h")
    lkm = b.groupby(b.index.floor("h")).size()
    taydet = lkm.index[1:-1]  # ensimmäinen ja viimeinen tunti voivat olla vajaita
    ol = oma.index.intersection(h1_duk.index).intersection(taydet)
    if len(ol) > 24:
        ero = (oma.loc[ol] - h1_duk.loc[ol]).abs().max().max()
        if ero > 1.0:
            virheet.append(f"H1-kynttilät eivät täsmää minuuttidataan (ero {ero:.2f} $)")
        huom.append(f"H1 vs M1 suurin ero {ero:.2f} $ ({len(ol)} tuntia)")
    else:
        virheet.append("H1- ja M1-data eivät mene päällekkäin")
    if nyt is not None:
        ika = (nyt - b.index[-1]).total_seconds() / 60 - 1
        auki = not (nyt.tz_convert(NY).weekday() == 5 or
                    (nyt.tz_convert(NY).weekday() == 4 and nyt.tz_convert(NY).hour >= 17) or
                    (nyt.tz_convert(NY).weekday() == 6 and nyt.tz_convert(NY).hour < 18))
        if auki and ika > 15:
            virheet.append(f"VANHA DATA: viimeisin minuutti {ika:.0f} min sitten")
        huom.append(f"datan ikä {max(ika, 0):.0f} min")
    viim = b[b.index >= b.index[-1] - pd.Timedelta(hours=3)]
    puuttuu = 180 - len(viim)
    if puuttuu > 20:
        huom.append(f"viim. 3 h:sta puuttuu {puuttuu} minuuttia (markkinatauko tai syöttökatko)")
    return virheet, huom


# ---------------------------------------------------------------- kuva

def piirra(k, sw, tap, zones, fv, tasot, hinta, otsikko, polku, n_naytto):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    alku = max(0, len(k) - n_naytto)
    kk = k.iloc[alku:]
    x = np.arange(len(kk))
    fig, ax = plt.subplots(figsize=(16, 8), dpi=110)
    lev = 0.6
    for xi, (o, h, l, c) in zip(x, kk[["open", "high", "low", "close"]].values):
        vari = "#1a9850" if c >= o else "#d73027"
        ax.vlines(xi, l, h, color=vari, lw=0.8)
        ax.add_patch(Rectangle((xi - lev / 2, min(o, c)), lev, max(abs(c - o), 0.01), color=vari))
    oikea = len(kk) + 6
    alin, ylin = kk.low.min(), kk.high.max()
    pad = (ylin - alin) * 0.05
    for z in zones:
        if z["mitatoity"] or z["kaynnit"] >= 3 or z["i"] < alku:
            continue
        x0 = z["i"] - alku
        vari = "#2b83ba" if z["suunta"] == 1 else "#d7191c"
        ax.add_patch(Rectangle((x0, z["ala"]), oikea - x0, z["yla"] - z["ala"], color=vari, alpha=0.18, lw=0))
        if z["ala"] <= ylin + pad and z["yla"] >= alin - pad:
            ax.text(oikea, min(max((z["ala"] + z["yla"]) / 2, alin), ylin), f" {'kysyntä' if z['suunta'] == 1 else 'tarjonta'} "
                    f"{z['ala']:.1f}–{z['yla']:.1f}", va="center", fontsize=8, color=vari, clip_on=True)
    for f in fv:
        if f["taytetty"] or f["i"] < alku:
            continue
        x0 = f["i"] - 2 - alku
        ax.add_patch(Rectangle((x0, f["ala"]), oikea - x0, f["yla"] - f["ala"], fill=False, hatch="///",
                               edgecolor="#7b3294", alpha=0.5, lw=0.5))
    for e in tap:
        if e["swing_i"] < alku:
            continue
        x0, x1 = e["swing_i"] - alku, e["j"] - alku
        vari = "#1a9850" if e["suunta"] == 1 else "#d73027"
        ax.hlines(e["taso"], x0, x1, color=vari, lw=1, ls="-")
        ax.text((x0 + x1) / 2, e["taso"], e["tyyppi"], fontsize=7, color=vari, ha="center",
                va="bottom" if e["suunta"] == 1 else "top")
    for i, t, lv in sw:
        if i >= alku:
            ax.plot(i - alku, lv, marker="v" if t == "H" else "^", color="#555", ms=3)
    for o in tasot:
        if not (alin - pad <= o["taso"] <= ylin + pad):
            continue
        ax.axhline(o["taso"], color="#f39c12", lw=0.8, ls="--")
        ax.text(0, o["taso"], f"{o['nimi']} {o['taso']:.1f}" + (" ✓pyyhk." if o["pyyhkaisty"] else ""),
                fontsize=7, color="#b9770e", va="bottom", clip_on=True)
    ax.axhline(hinta, color="black", lw=0.8)
    ax.text(oikea, hinta, f" nyt {hinta:.2f}", va="center", fontsize=9, fontweight="bold")
    paikat = np.linspace(0, len(kk) - 1, min(12, len(kk))).astype(int)
    ax.set_xticks(paikat)
    ax.set_xticklabels([kk.index[p].tz_convert(HKI).strftime("%d.%m %H:%M") for p in paikat], fontsize=8, rotation=30)
    ax.set_xlim(-1, oikea + 14)
    ax.set_ylim(alin - pad, ylin + pad)
    ax.grid(alpha=0.2)
    ax.set_title(otsikko + " (Suomen aika, bid)")
    fig.tight_layout()
    fig.savefig(polku)
    plt.close(fig)
    # tarkistus: piirretty viimeinen kynttilä = data
    return dict(kynttiloita=len(kk), viimeinen=kk.index[-1].tz_convert(HKI).strftime("%d.%m. %H:%M"),
                viimeinen_sulku=float(kk.close.iloc[-1]))


# ---------------------------------------------------------------- pääohjelma

def analysoi(kansio, ulos, aika=None):
    os.makedirs(ulos, exist_ok=True)
    b, a = lue(f"{kansio}/m1_bid.csv"), lue(f"{kansio}/m1_ask.csv")
    h1_duk = lue(f"{kansio}/h1_bid.csv")
    nyt = None
    if aika:
        t = pd.Timestamp(aika, tz=HKI).tz_convert("UTC")
    else:
        nyt = pd.Timestamp(datetime.now(timezone.utc))
        t = b.index[-1] + pd.Timedelta(minutes=1)
    b, a = b[b.index < t], a[a.index < t]
    h1_duk = h1_duk[h1_duk.index + pd.Timedelta(hours=1) <= t]
    virheet, huom = tarkista(b, a, h1_duk, nyt)

    # kynttilät: vanha historia Dukascopyn H1:stä, minuuttidatan ajalta minuuteista koottuna
    h1_m = suljetut(kynttilat(b, "1h"), pd.Timedelta(hours=1), t)
    h1 = pd.concat([h1_duk[h1_duk.index < h1_m.index[0]], h1_m])
    h4 = suljetut(kynttilat(h1, "4h", NY, "1h"), pd.Timedelta(hours=4), t)
    d1 = paivat(h1)
    d1 = d1[d1.index < paivan_alku(t)]  # vain sulkeutuneet päivät
    m15 = suljetut(kynttilat(b, "15min"), pd.Timedelta(minutes=15), t)
    m5 = suljetut(kynttilat(b, "5min"), pd.Timedelta(minutes=5), t)
    bid, ask = float(b.close.iloc[-1]), float(a.close.iloc[-1])

    tf = {"D": d1, "H4": h4, "H1": h1, "M15": m15, "M5": m5}
    R = {}
    for nimi, k in tf.items():
        a_ = atr(k)
        tr, tap, sw = rakenne(k, SWING_N[nimi])
        fv = fvgt(k, a_)
        zs = vyohykkeet(k, tap, fv, a_)
        R[nimi] = dict(k=k, atr=a_, trendi=tr, tap=tap, sw=sw, fv=fv, zs=zs)

    # premium/discount H4- ja H1-alueella
    def alue(nimi):
        r = R[nimi]
        k, sw = r["k"], r["sw"]
        n = SWING_N[nimi]
        hs = [s for s in sw if s[1] == "H" and s[0] + n < len(k)]
        ls = [s for s in sw if s[1] == "L" and s[0] + n < len(k)]
        if not hs or not ls:
            return None
        hi_i, lo_i = hs[-1][0], ls[-1][0]
        hi = max(hs[-1][2], float(k.high.iloc[hi_i:].max()))
        lo = min(ls[-1][2], float(k.low.iloc[lo_i:].min()))
        return dict(ala=lo, yla=hi, sijainti=round((bid - lo) / (hi - lo) * 100) if hi > lo else None)

    lik, tanaan = likviditeetti(b, d1, R["H1"]["sw"], h1, m15, R["M15"]["sw"], t, R["H1"]["atr"])

    def aikaf(k, i):
        return k.index[i].tz_convert(HKI).strftime("%d.%m. %H:%M")

    rivit = []
    hk = t.tz_convert(HKI)
    rivit.append(f"ANALYYSI {hk:%d.%m.%Y %H:%M} Suomen aikaa (viimeisin minuutti {b.index[-1].tz_convert(HKI):%H:%M})")
    rivit.append(f"Hinta: bid {bid:.2f} / ask {ask:.2f} (spread {ask - bid:.2f})")
    rivit.append("ATR (keskim. kynttilän koko): " + " | ".join(f"{n} {R[n]['atr']:.1f}" for n in ("D", "H4", "H1", "M15")))
    rivit.append("")
    rivit.append("RAKENNE (trendi = viimeisimmän murron suunta)")
    sanat = {1: "NOUSU", -1: "LASKU", 0: "ei selvä"}
    for n in ("D", "H4", "H1", "M15", "M5"):
        r = R[n]
        viim = r["tap"][-3:]
        kuvaus = "; ".join(f"{e['tyyppi']} {'ylös' if e['suunta'] == 1 else 'alas'} {aikaf(r['k'], e['j'])} @ {e['taso']:.1f}"
                           for e in viim)
        rivit.append(f"  {n:4s} {sanat[r['trendi']]:8s} viim. murrot: {kuvaus or '-'}")
    for n in ("H4", "H1"):
        al = alue(n)
        if al:
            pd_ = "PREMIUM (kallis, myyntialue)" if al["sijainti"] > 50 else "DISCOUNT (halpa, ostoalue)"
            rivit.append(f"  {n}-alue {al['ala']:.1f}–{al['yla']:.1f}: hinta {al['sijainti']} % -> {pd_}")
    rivit.append("")
    rivit.append("VYÖHYKKEET (voimassa, lähimmät ensin; käynnit = montako kertaa hinta palannut, 3+ = kulunut, ei näytetä)")
    zt = []
    for n in ("H4", "H1", "M15"):
        r = R[n]
        for z in r["zs"]:
            if z["mitatoity"] or z["kaynnit"] >= 3:
                continue
            etaisyys = (bid - z["yla"]) if z["suunta"] == 1 else (z["ala"] - bid)
            if abs(etaisyys) > 3 * R["D"]["atr"]:
                continue
            zt.append((n, z, etaisyys, aikaf(r["k"], z["i"])))
    for puoli, otsikko in ((1, "Kysyntä (alapuolella)"), (-1, "Tarjonta (yläpuolella)")):
        lista = sorted([x for x in zt if x[1]["suunta"] == puoli], key=lambda x: abs(x[2]))[:6]
        rivit.append(f"  {otsikko}:")
        for n, z, et, ai in lista:
            sis = " HINTA VYÖHYKKEELLÄ" if z["ala"] <= bid <= z["yla"] else f" {abs(et):.1f} $ päässä"
            levea = ", LEVEÄ" if (z["yla"] - z["ala"]) > 1.5 * R[n]["atr"] else ""
            rivit.append(f"    {n:3s} {z['ala']:.1f}–{z['yla']:.1f} ({ai}, {z['murto']}"
                         f"{', voimakas lähtö' if z['siirtyma'] else ''}, käynnit {z['kaynnit']}{levea}){sis}")
        if not lista:
            rivit.append("    -")
    rivit.append("")
    rivit.append("FVG (täyttämättömät aukot, H1 ja M15)")
    for n in ("H1", "M15"):
        r = R[n]
        av = [f for f in r["fv"] if not f["taytetty"] and abs((f["ala"] + f["yla"]) / 2 - bid) < 2 * R["D"]["atr"]][-4:]
        for f in av:
            rivit.append(f"    {n:3s} {'nouseva' if f['suunta'] == 1 else 'laskeva'} {f['ala']:.1f}–{f['yla']:.1f} "
                         f"({aikaf(r['k'], f['i'])}{', osittain täytetty' if f['osittain'] else ''})")
    rivit.append("")
    rivit.append("LIKVIDITEETTI (stoppien kasaumat)")
    for o in sorted(lik, key=lambda o: -o["taso"]):
        tila = "ei pyyhkäisty"
        if o["pyyhkaisty"]:
            tila = f"pyyhkäisty {o['pyyhkaisty']}" + (" ja sulki takaisin" if o["sulki_takaisin"] else "")
        rivit.append(f"    {o['nimi']:26s} {o['taso']:.1f}  {tila}")
    if len(tanaan):
        rivit.append(f"  Tämän päivän (NY-päivä) alue: {tanaan.low.min():.1f}–{tanaan.high.max():.1f}")
    rivit.append("")
    rivit.append("TARKISTUS")
    for v in virheet:
        rivit.append(f"  VIRHE: {v}")
    for h in huom:
        rivit.append(f"  ok: {h}")

    kuvat = {}
    tasot_kuvaan = [o for o in lik if not o["nimi"].startswith("Tasaiset")]
    kuvat["h1"] = piirra(h1, R["H1"]["sw"], R["H1"]["tap"], R["H1"]["zs"],
                         R["H1"]["fv"], tasot_kuvaan, bid, f"XAU/USD H1 {hk:%d.%m. %H:%M}", f"{ulos}/h1.png", 120)
    kuvat["m15"] = piirra(m15, R["M15"]["sw"], R["M15"]["tap"], R["M15"]["zs"], R["M15"]["fv"],
                          lik, bid, f"XAU/USD M15 {hk:%d.%m. %H:%M}", f"{ulos}/m15.png", 160)
    for nimi, kv in kuvat.items():
        k = h1 if nimi == "h1" else m15
        if abs(kv["viimeinen_sulku"] - float(k.close.iloc[-1])) > 1e-6:
            virheet.append(f"kuva {nimi}: viimeinen kynttilä ei vastaa dataa")
    rivit.append(f"  ok: kuvat piirretty, viimeinen H1-kynttilä {kuvat['h1']['viimeinen']}, "
                 f"viimeinen M15-kynttilä {kuvat['m15']['viimeinen']} (Suomen aikaa, alkuhetki)")

    teksti = "\n".join(rivit)
    open(f"{ulos}/analyysi.txt", "w").write(teksti)
    js = dict(aika_hki=hk.strftime("%Y-%m-%d %H:%M"), viimeinen_minuutti_utc=b.index[-1].isoformat(), bid=bid, ask=ask,
              atr={n: round(R[n]["atr"], 2) for n in R}, trendi={n: R[n]["trendi"] for n in R},
              alueet={n: alue(n) for n in ("H4", "H1")},
              vyohykkeet=[dict(tf=n, suunta=z["suunta"], ala=z["ala"], yla=z["yla"], syntyi=ai, murto=z["murto"],
                               voimakas=z["siirtyma"], kaynnit=z["kaynnit"]) for n, z, _, ai in zt],
              likviditeetti=[{k_: v for k_, v in o.items() if k_ != "alku"} for o in lik],
              virheet=virheet, huomiot=huom)
    json.dump(js, open(f"{ulos}/analyysi.json", "w"), ensure_ascii=False, indent=1, default=str)
    print(teksti)
    return virheet


if __name__ == "__main__":
    args = sys.argv[1:]
    aika = None
    if "--aika" in args:
        i = args.index("--aika")
        aika = args[i + 1]
        del args[i:i + 2]
    v = analysoi(args[0], args[1], aika)
    sys.exit(2 if v else 0)
