"""News Impact Tracker — motore. Misura ed espone. Non prevede.
Ogni numero porta data, fonte, finestra, benchmark. Gira ogni 4h su GitHub Actions."""
import os, re, time
import numpy as np, pandas as pd, yfinance as yf, feedparser
from datetime import date
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = "Arial"

NERO, FUCSIA, BIANCO, GRIGIO = "#0C0C11", "#ff2fb0", "#F4F4F6", "#B0AAAB"

# ============ CONFIGURAZIONE ============
FEED_ESG = {
    "ESG Today":  "https://www.esgtoday.com/feed/",
    "ESG Dive":   "https://www.esgdive.com/feeds/news/",
    "ESG News":   "https://esgnews.com/feed/",
    "Responsible Investor": "https://www.responsible-investor.com/feed/",
}
BLACKLIST = {"Motley Fool"}
AMBIGUI = {"target","amazon","apple","shell","gap","match","ball","corning","carnival",
           "centene","first solar","public storage","expedia","align","assurant","best buy",
           "charter","edison","host","masco","news","paramount","principal","progressive",
           "republic","sempra","synopsys","tapestry","teleflex","universal","valero"}

# Fonte: CFA Sustainable Investing 2.07 (SASB Materiality Map)
TAG_E = ["ghg","greenhouse","emission","carbon","net zero","net-zero","climate","air quality",
         "pollut","energy management","renewable","renew","clean energy","solar","wind",
         "nuclear","water","wastewater","waste","hazardous","ecological","biodiversity",
         "deforestation","reforestation","nature","circular","recycl","scope 1","scope 2",
         "scope 3","sbti","science-based","energy","power","grid","green","sustainab",
         "transition","fossil","coal","oil","gas","battery","electric"]
# Fonte: CFA 3.06
TAG_S = ["labor","labour","child labor","modern slavery","human rights","supply chain",
         "health and safety","workplace","layoff","strike","union","discriminat","harassment",
         "diversity","inequality","wage","worker","employee","data privacy","community",
         "resettlement"]
# Fonte: CFA 4.07
TAG_G = ["board","director","shareholder","proxy","vote","executive pay","remuneration",
         "audit","fraud","bribery","corruption","antitrust","sec charges","investigation",
         "governance","whistleblower","disclosure","greenwash","csrd","issb","ifrs s1",
         "ifrs s2","tcfd","sfdr"]
# Fonte: CFA 2.07/2.08/3.06/4.07 — approssimazione GICS della SASB Materiality Map
MATERIALE = {
    "Energy":(True,True,True), "Materials":(True,True,True), "Utilities":(True,False,True),
    "Industrials":(True,True,True), "Consumer Staples":(True,True,True),
    "Real Estate":(True,False,True), "Consumer Discretionary":(False,True,True),
    "Health Care":(False,True,True), "Information Technology":(False,True,True),
    "Communication Services":(False,True,True), "Financials":(False,False,True),
}
# Fonte: CFA 1.05 Exhibit 4 (McKinsey)
EBITDA_RISCHIO = {"Information Technology":0.55,"Industrials":0.50,"Communication Services":0.45,
    "Energy":0.40,"Materials":0.40,"Utilities":0.40,"Financials":0.35,"Real Estate":0.35,
    "Consumer Discretionary":0.275,"Consumer Staples":0.275,"Health Care":0.275}

# ============ UNIVERSO ============
UNIVERSO = pd.read_csv("universo_v3.csv")

def pulisci(n):
    n = str(n).lower()
    for s in [" inc."," inc"," corporation"," corp."," corp"," company"," co.",
              " plc"," ltd"," group"," holdings"," & co"," the ",",","."]:
        n = n.replace(s, "")
    return n.strip()

NOME2TICK = {pulisci(r["nome"]): r["ticker"] for _, r in UNIVERSO.iterrows()
             if r["tipo"] == "stock" and len(pulisci(r["nome"])) >= 5}
TICK2NOME = {r["ticker"]: pulisci(r["nome"]) for _, r in UNIVERSO.iterrows()}
SETTORE   = dict(zip(UNIVERSO["ticker"], UNIVERSO["settore"]))
TIPO      = dict(zip(UNIVERSO["ticker"], UNIVERSO["tipo"]))
BENCH_NOME = {"^GSPC":"S&P 500", "^STOXX50E":"Euro Stoxx 50", "^FTSE":"FTSE 100",
              "^GDAXI":"DAX", "^IXIC":"Nasdaq"}
BENCH     = dict(zip(UNIVERSO["ticker"], UNIVERSO["bench"]))
WATCH_YF  = sorted(set(pd.read_csv("pesi.csv")["ticker"]) & set(UNIVERSO["ticker"]))

# ============ FUNZIONI ============
def giorno_zero(pub_utc):
    t = pd.Timestamp(pub_utc).tz_convert("America/New_York")
    if t.hour >= 16: t = t + pd.Timedelta(days=1)
    return t.normalize().tz_localize(None)

def tag_esg(titolo):
    t = str(titolo).lower()
    return "".join(n for n, kw in [("E",TAG_E),("S",TAG_S),("G",TAG_G)] if any(k in t for k in kw))

def materiale(tag, settore):
    m = MATERIALE.get(settore)
    if not m or not tag or pd.isna(tag): return None
    return any(m[i] for i, l in enumerate("ESG") if l in str(tag))

def trova_ticker(titolo):
    t = " " + str(titolo).lower() + " "
    hit = set()
    for nome, tk in NOME2TICK.items():
        m = re.search(r"\b" + re.escape(nome) + r"\b", t)
        if not m: continue
        if nome in AMBIGUI and m.start() > len(t) * 0.35: continue
        hit.add(tk)
    return list(hit)[0] if len(hit) == 1 else None

def rilevante(titolo, ticker, fonte=None):
    if fonte in BLACKLIST: return False
    t = " " + str(titolo).lower() + " "
    if re.search(r"\b" + re.escape(ticker.lower()) + r"\b", t): return True
    nome = TICK2NOME.get(ticker, "")
    if not nome or len(nome) < 5: return False
    m = re.search(r"\b" + re.escape(nome) + r"\b", t)
    if not m: return False
    if nome in AMBIGUI and m.start() > len(t) * 0.35: return False
    return True

def notizie(ticker, max_n=8):
    try:
        raw = yf.Ticker(ticker).news
    except Exception as e:
        print(f"  x {ticker}: {str(e)[:40]}"); return pd.DataFrame()
    righe = []
    for it in raw:
        c = it.get("content") or {}
        if c.get("contentType") != "STORY" or not c.get("pubDate"): continue
        righe.append({"id": it.get("id"), "ticker": ticker, "pub_utc": c["pubDate"],
                      "giorno0": str(giorno_zero(c["pubDate"]).date()),
                      "titolo": c.get("title"),
                      "fonte": (c.get("provider") or {}).get("displayName"),
                      "link": (c.get("canonicalUrl") or {}).get("url")})
    return pd.DataFrame(righe[:max_n])

def notizie_esg():
    righe = []
    for fonte, url in FEED_ESG.items():
        try:
            entries = feedparser.parse(url).entries
        except Exception as e:
            print(f"  x {fonte}: {str(e)[:40]}"); continue
        for e in entries:
            tk = trova_ticker(e.get("title", ""))
            if not tk or not e.get("published_parsed"): continue
            pub = pd.Timestamp(*e.published_parsed[:6], tz="UTC")
            righe.append({"id": e.get("id", e.link), "ticker": tk, "fonte": fonte,
                          "titolo": e.title, "link": e.link, "pub_utc": str(pub),
                          "giorno0": str(giorno_zero(str(pub)).date()),
                          "settore": SETTORE.get(tk)})
    return pd.DataFrame(righe)

def car(ticker, data_notizia, PX, bench="^GSPC", ev=(-1,3),
        stima_fine=-11, stima_lung=120, w_graf=63):
    if ticker not in PX.columns or bench not in PX.columns:
        return {"ok": False, "motivo": "ticker non in cache"}
    px = PX[[ticker, bench]].dropna()
    if len(px) < 200: return {"ok": False, "motivo": "storico insufficiente"}
    ret = px.pct_change().dropna()
    PXa, giorni = px.loc[ret.index], ret.index
    t0 = giorni.searchsorted(pd.Timestamp(data_notizia))
    if t0 >= len(giorni): return {"ok": False, "motivo": "fuori dallo storico"}
    s0, s1 = t0 + stima_fine - stima_lung + 1, t0 + stima_fine
    e0, e1 = t0 + ev[0], t0 + ev[1]
    if s0 < 0:            return {"ok": False, "motivo": "storico insufficiente"}
    if e1 >= len(giorni): return {"ok": False, "motivo": "in consolidamento"}
    x, y = ret[bench].iloc[s0:s1+1].values, ret[ticker].iloc[s0:s1+1].values
    beta, alfa = np.polyfit(x, y, 1)
    sigma = (y - (alfa + beta*x)).std(ddof=2)
    ar = ret[ticker] - (alfa + beta*ret[bench])
    c = ar.iloc[e0:e1+1].sum()
    soglia = 1.96 * sigma * np.sqrt(ev[1]-ev[0]+1)
    g0, g1 = max(t0-w_graf, 0), min(t0+w_graf, len(giorni)-1)
    base = t0 - 1
    asse = np.arange(g0, g1+1) - t0
    tit = PXa[ticker].iloc[g0:g1+1].values / PXa[ticker].iloc[base] * 100
    ben = PXa[bench].iloc[g0:g1+1].values / PXa[bench].iloc[base] * 100
    lo = np.full(len(asse), np.nan); hi = lo.copy()
    j = base - g0; lo[j] = hi[j] = 100.0; liv = 100.0
    for k in range(1, len(asse)-j):
        liv *= (1 + alfa + beta*ret[bench].iloc[g0+j+k])
        b = 1.96*sigma*np.sqrt(k)
        lo[j+k], hi[j+k] = liv*(1-b), liv*(1+b)
    return {"ok": True, "ticker": ticker, "bench": bench, "data": str(giorni[t0].date()),
            "ev": ev, "car": float(c), "soglia": float(soglia), "rumore": bool(abs(c)<soglia),
            "beta": float(beta), "alfa": float(alfa), "sigma": float(sigma),
            "asse": asse, "tit": tit, "ben": ben, "lo": lo, "hi": hi}

def disegna(ev_id, ticker, s, banda=True, bench="benchmark"):
    os.makedirs("grafici", exist_ok=True)
    p = f"grafici/{ev_id.replace('|','_').replace('^','I')}{'' if banda else '_nb'}.png"
    if os.path.exists(p): return p
    fig, ax = plt.subplots(figsize=(11, 5.5), facecolor=NERO, dpi=100)
    ax.set_facecolor(NERO)
    if banda:
        ax.fill_between(s["asse"], s["lo"], s["hi"], color=GRIGIO, alpha=.22, lw=0, zorder=1)
    ax.plot(s["asse"], s["ben"], color=BIANCO, lw=1.0, alpha=.75, zorder=2, label=bench)
    for lw, al in [(9,.04),(6,.06),(3.5,.12)]:
        ax.plot(s["asse"], s["tit"], color=FUCSIA, lw=lw, alpha=al, zorder=3, solid_capstyle="round")
    ax.plot(s["asse"], s["tit"], color=FUCSIA, lw=1.9, zorder=4, label=ticker)
    ax.axvline(0, color=BIANCO, ls=(0,(5,4)), lw=1.2, alpha=.9, zorder=5)
    for sp in ax.spines.values(): sp.set_visible(False)
    ax.tick_params(colors=GRIGIO, labelsize=9)
    ax.grid(axis="y", color=GRIGIO, alpha=.10, lw=.6); ax.set_axisbelow(True)
    ax.set_xticks([-60,-30,0,30,60])
    ax.set_xlabel("trading days from news", color=GRIGIO, fontsize=9)
    ax.set_ylabel("rebased to 100", color=GRIGIO, fontsize=9)
    ax.set_title(f"{ticker} · {ev_id.split('|')[1]}", color=BIANCO, fontsize=12, loc="left", pad=14)
    ax.text(0, ax.get_ylim()[1], "  news", color=BIANCO, fontsize=9, va="top")
    leg = ax.legend(loc="lower left", frameon=False, fontsize=9)
    for t in leg.get_texts(): t.set_color(BIANCO)
    fig.tight_layout(); fig.savefig(p, facecolor=NERO); plt.close(fig)
    return p


def leggi(nome, colonne):
    if not os.path.exists(nome): return pd.DataFrame(columns=colonne)
    d = pd.read_csv(nome)
    if not set(colonne) <= set(d.columns):
        print(f"  ! {nome} schema vecchio — riparto"); return pd.DataFrame(columns=colonne)
    return d

def stato(riga, PX):
    r = car(riga["ticker"], riga["giorno0"], PX, bench=BENCH.get(riga["ticker"], "^GSPC"))
    base = {k: riga.get(k) for k in ["ticker","mondo","tag","materiale","settore","giorno0","evento"]}
    base["tipo"]  = TIPO.get(riga["ticker"], "stock")
    base["bench"] = BENCH_NOME.get(BENCH.get(riga["ticker"], "^GSPC"), "market")
    if not r["ok"]:
        m = r["motivo"]
        st = ("consolidating" if "consolidamento" in m
              else "waiting" if "fuori dallo storico" in m else "no data")
        return {**base, "stato": st, "car": None, "soglia": None, "rumore": None,
                "beta": None, "sigma": None}, None
    serie = pd.DataFrame({"evento": riga["evento"], "asse": r["asse"], "tit": r["tit"],
                          "ben": r["ben"], "lo": r["lo"], "hi": r["hi"]})
    return {**base, "stato": "closed", "car": round(r["car"]*100,2),
            "soglia": round(r["soglia"]*100,2), "rumore": bool(r["rumore"]),
            "beta": round(r["beta"],2), "sigma": round(r["sigma"]*100,2)}, serie

def aggiorna_prezzi():
    tutti = sorted(set(UNIVERSO["ticker"]) | set(UNIVERSO["bench"]))
    if os.path.exists("prezzi.csv"):
        vecchi = pd.read_csv("prezzi.csv", index_col=0, parse_dates=True)
        da = vecchi.index.max() - pd.Timedelta(days=7)
    else:
        vecchi, da = pd.DataFrame(), pd.Timestamp(date.today()) - pd.Timedelta(days=730)
    parti = []
    for i in range(0, len(tutti), 50):
        b = tutti[i:i+50]
        for k in range(3):
            try:
                parti.append(yf.download(b, start=str(da.date()), auto_adjust=True,
                                         progress=False)["Close"]); break
            except Exception as e:
                print(f"  ritento {k+1}/3: {str(e)[:40]}"); time.sleep(20)
        time.sleep(4)
    nuovi = pd.concat(parti, axis=1)
    PX = nuovi if not len(vecchi) else vecchi.combine_first(nuovi)
    PX = PX.loc[:, PX.notna().sum() >= 400].sort_index()
    PX.to_csv("prezzi.csv")
    print(f"prezzi.csv — {PX.shape[0]}g × {PX.shape[1]}t · ultimo {PX.index.max().date()}")
    return PX

def giro(PX):
    a = notizie_esg()
    if len(a): a["tag"] = a["titolo"].map(tag_esg); a["mondo"] = "ESG"
    b = pd.concat([notizie(t) for t in WATCH_YF], ignore_index=True)
    if len(b):
        b = b[[rilevante(r["titolo"], r["ticker"], r["fonte"]) for _, r in b.iterrows()]].copy()
        b["tag"] = b["titolo"].map(tag_esg)
        b["settore"] = b["ticker"].map(SETTORE)
        b["mondo"] = np.where(b["tag"] != "", "ESG", "General")
    nz = pd.concat([x for x in (a, b) if len(x)], ignore_index=True)
    nz["materiale"] = [materiale(r["tag"], r["settore"]) for _, r in nz.iterrows()]
    nz["evento"] = nz["ticker"] + "|" + nz["giorno0"]
    nz["chiave"] = nz["id"].astype(str) + "|" + nz["ticker"]

    NZ = pd.concat([leggi("notizie.csv", ["chiave"]), nz], ignore_index=True)
    NZ = NZ.drop_duplicates(subset="chiave", keep="last")
    NZ.to_csv("notizie.csv", index=False)

    ev_map = NZ.groupby("evento").agg(
        mondo=("mondo", lambda s: "ESG" if (s=="ESG").any() else "General"),
        tag=("tag", lambda s: "".join(sorted(set("".join(s.dropna().astype(str)))))),
        materiale=("materiale","max"), settore=("settore","first"),
        ticker=("ticker","first"), giorno0=("giorno0","first")).reset_index()

    EVv = leggi("eventi.csv", ["evento","stato"])
    chiusi = set(EVv.loc[EVv["stato"]=="closed","evento"]) if len(EVv) else set()
    da_fare = ev_map[~ev_map["evento"].isin(chiusi)]
    print(f"{len(NZ)} notizie → {len(ev_map)} eventi · {len(da_fare)} da calcolare · {len(chiusi)} congelati")

    righe, ser = [], []
    for _, r in da_fare.iterrows():
        s, sr = stato(r, PX)
        righe.append(s)
        if sr is not None:
            ser.append(sr)
            nb = BENCH_NOME.get(BENCH.get(r["ticker"], "^GSPC"), "benchmark")
            disegna(r["evento"], r["ticker"], sr, bench=nb)
            disegna(r["evento"], r["ticker"], sr, banda=False, bench=nb)

    if ser:
        S = pd.concat([leggi("serie.csv", ["evento","asse"])] + ser, ignore_index=True)
        S.drop_duplicates(subset=["evento","asse"], keep="last").to_csv("serie.csv", index=False)

    # disegna i PNG mancanti da serie.csv — anche per gli eventi congelati
    if os.path.exists("serie.csv"):
        for ev_id, g in pd.read_csv("serie.csv").groupby("evento"):
            tk = ev_id.split("|")[0]
            nb = BENCH_NOME.get(BENCH.get(tk, "^GSPC"), "benchmark")
            disegna(ev_id, tk, g, bench=nb)
            disegna(ev_id, tk, g, banda=False, bench=nb)

    EV = pd.concat([EVv, pd.DataFrame(righe)], ignore_index=True)
    EV = EV.drop_duplicates(subset="evento", keep="last").sort_values("giorno0", ascending=False)
    EV.to_csv("eventi.csv", index=False)
    print(f"eventi.csv — {len(EV)} · {EV['stato'].value_counts().to_dict()}")
    print(f"  ESG {(EV['mondo']=='ESG').sum()} · General {(EV['mondo']=='General').sum()}")
    print(f"  grafici: {len(os.listdir('grafici')) if os.path.exists('grafici') else 0} PNG")
    return EV, NZ

if __name__ == "__main__":
    print(f"universo: {len(UNIVERSO)} · watchlist Yahoo: {len(WATCH_YF)}")
    PX = aggiorna_prezzi()
    giro(PX)
    print("giro completato")
