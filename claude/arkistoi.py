"""Arkistoi analyysin ja kaikki chartit pysyvästi haaraan "arkisto" kauppahetkien kohdalla.

Hinnat-haara kirjoitetaan yli minuutin välein, joten vanhat chartit katoavat. Tämä tallentaa jokaisen
kauppahetken (ajat.txt:n [kauppa]-rivit) tilanteen kansioon arkisto/YYYY-MM-DD/HHMM/, jotta vanhoja
päätöksiä voi verrata silloisiin chartteihin.

Käyttö (GitHub Actionsissa, GH_TOKEN ja GITHUB_REPOSITORY ympäristössä):
  python arkistoi.py LAHDE                 arkistoi, jos jokin kauppahetki oli 1–6 min sitten
  python arkistoi.py LAHDE --nyt           arkistoi heti kansioon tämän hetken mukaan (testi)
LAHDE = julkaistava kansio (meta.json, ajat.txt, anal/...).
Ympäristö: ARK_HAARA (oletus "arkisto"), ARK_MERKIT (oletus /tmp/ark_tehty).
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

HKI = ZoneInfo("Europe/Helsinki")
TIEDOSTOT = ["meta.json", "anal/analyysi.txt", "anal/analyysi.json", "anal/d1.png", "anal/h4.png", "anal/h1.png",
             "anal/m15.png", "anal/m5.png", "anal/m1.png", "anal/s10.png"]


def api(metodi, polku, data=None):
    url = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{polku}"
    req = urllib.request.Request(url, method=metodi, data=None if data is None else json.dumps(data).encode())
    req.add_header("Authorization", f"Bearer {os.environ['GH_TOKEN']}")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def blob(sisalto):
    return api("POST", "/git/blobs", dict(content=base64.b64encode(sisalto).decode(), encoding="base64"))["sha"]


def arkistoi(lahde, kohde, haara):
    try:
        paa = api("GET", f"/git/ref/heads/{haara}")["object"]["sha"]
        puu = api("GET", f"/git/commits/{paa}")["tree"]["sha"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        # haaraa ei ole: luo se tyhjästä (ei yhteistä historiaa koodin kanssa)
        ohje = (b"Clauden kauppahetkien analyysit ja chartit: YYYY-MM-DD/HHMM/ (Suomen aikaa).\n"
                b"Tiedostot: analyysi.txt, analyysi.json, meta.json, d1/h4/h1/m15/m5/m1/s10.png\n")
        puu = api("POST", "/git/trees", dict(tree=[dict(path="LUEMINUT.txt", mode="100644", type="blob",
                                                         sha=blob(ohje))]))["sha"]
        paa = api("POST", "/git/commits", dict(message="Arkisto alkaa", tree=puu, parents=[]))["sha"]
        api("POST", "/git/refs", dict(ref=f"refs/heads/{haara}", sha=paa))
    rivit = []
    for f in TIEDOSTOT:
        p = f"{lahde}/{f}"
        if os.path.exists(p):
            rivit.append(dict(path=f"{kohde}/{os.path.basename(f)}", mode="100644", type="blob",
                              sha=blob(open(p, "rb").read())))
    if not rivit:
        print("ei arkistoitavaa")
        return False
    uusi_puu = api("POST", "/git/trees", dict(base_tree=puu, tree=rivit))["sha"]
    uusi = api("POST", "/git/commits", dict(message=f"Arkisto {kohde}", tree=uusi_puu, parents=[paa]))["sha"]
    api("PATCH", f"/git/refs/heads/{haara}", dict(sha=uusi))
    print(f"arkistoitu {kohde}: {len(rivit)} tiedostoa")
    return True


def kauppahetket(ajat_txt):
    out = []
    for r in open(ajat_txt, encoding="utf-8"):
        if r.startswith("---"):
            break
        if "[kauppa]" in r:
            out.append(r.split()[0])  # "HH:MM" Suomen aikaa
    return out


def main(lahde, heti=False):
    haara = os.environ.get("ARK_HAARA", "arkisto")
    merkit = os.environ.get("ARK_MERKIT", "/tmp/ark_tehty")
    os.makedirs(merkit, exist_ok=True)
    nyt = datetime.now(HKI)
    if heti:
        return arkistoi(lahde, nyt.strftime("%Y-%m-%d/%H%M"), haara)
    if not os.path.exists(f"{lahde}/ajat.txt"):
        return False
    for hm in kauppahetket(f"{lahde}/ajat.txt"):
        h, m = map(int, hm.split(":"))
        w = nyt.replace(hour=h, minute=m, second=0, microsecond=0)
        if timedelta(minutes=1) <= nyt - w <= timedelta(minutes=6):
            tunnus = w.strftime("%Y-%m-%d_%H%M")
            if os.path.exists(f"{merkit}/{tunnus}"):
                continue
            if arkistoi(lahde, w.strftime("%Y-%m-%d/%H%M"), haara):
                open(f"{merkit}/{tunnus}", "w").close()
    return True


if __name__ == "__main__":
    try:
        main(sys.argv[1], "--nyt" in sys.argv)
    except Exception as e:  # arkistointi ei saa kaataa hintasyötettä
        print("arkistointi epäonnistui:", type(e).__name__, e, file=sys.stderr)
