
"""Progetto Super — motore di misura.
Misura ed espone. Non prevede. Ogni numero porta l'etichetta di dove viene.
"""
import yfinance as yf
import pandas as pd
import numpy as np

GIORNI_BORSA = 252


def valida(tickers, inizio="2019-01-01", soglia_zeri=0.02):
    """Quali ticker esistono, hanno storico, e non hanno prezzi fermi?"""
    righe, scartati = [], []
    for t in tickers:
        try:
            d = yf.download(t, start=inizio, auto_adjust=True, progress=False)
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.droplevel("Ticker")
            s = d["Close"].dropna()
            if len(s) < 250:
                scartati.append((t, f"solo {len(s)} giorni")); continue
            zeri = int((s.pct_change().dropna() == 0).sum())
            righe.append({"ticker": t, "giorni": len(s), "zeri": zeri,
                          "%zeri": round(100 * zeri / len(s), 1),
                          "da": s.index.min().date(),
                          "usabile": zeri / len(s) < soglia_zeri})
        except Exception as e:
            scartati.append((t, str(e)[:40]))
    return pd.DataFrame(righe), scartati


def confronta(tickers, inizio="2019-01-01", fine=None, rf_annuo=0.0):
    """Scarica N ticker, li ALLINEA sui giorni comuni, ne calcola le metriche."""
    grezzi = yf.download(tickers, start=inizio, end=fine, auto_adjust=True, progress=False)
    px = grezzi["Close"].dropna()
    rend = px.pct_change().dropna()
    anni = len(rend) / GIORNI_BORSA
    rf_g = (1 + rf_annuo) ** (1 / GIORNI_BORSA) - 1
    righe = []
    for t in px.columns:
        r = rend[t]
        curva = (1 + r).cumprod()
        dd = curva / curva.cummax() - 1
        ex = r - rf_g
        righe.append({
            "ticker": t,
            "cagr_%": round(((px[t].iloc[-1] / px[t].iloc[0]) ** (1 / anni) - 1) * 100, 2),
            "vol_%": round(r.std() * np.sqrt(GIORNI_BORSA) * 100, 2),
            "sharpe": round(ex.mean() / ex.std() * np.sqrt(GIORNI_BORSA), 2),
            "max_dd_%": round(dd.min() * 100, 2),
            "gg_sott_acqua": int((dd < -0.0001).sum()),
            "zeri": int((r == 0).sum()),
        })
    tab = pd.DataFrame(righe).set_index("ticker")
    tab.attrs["periodo"] = f"{rend.index.min().date()} -> {rend.index.max().date()}"
    tab.attrs["giorni"] = len(rend)
    tab.attrs["rf_%"] = rf_annuo * 100
    tab.attrs["fonte"] = "yahoo / Close auto_adjust"
    return tab, px


def punteggio(tab, pesi=None, robusto=True):
    """Ordina secondo i pesi scelti. robusto=True usa il rango (immune agli outlier).
    NON dice quanto uno e' meglio. Dice solo in che ordine stanno, dati quei pesi."""
    if pesi is None:
        pesi = {"sharpe": 3, "ter_%": -2, "max_dd_%": 1, "vol_%": -1}
    out, contrib = tab.copy(), pd.DataFrame(index=tab.index)
    n = len(tab)
    for col, w in pesi.items():
        v = tab[col].astype(float)
        if robusto:
            norm = v.rank(method="average") / n * 100
        else:
            span = v.max() - v.min()
            norm = 50.0 if span == 0 else (v - v.min()) / span * 100
        contrib[col] = norm * w
    tot = sum(abs(w) for w in pesi.values())
    out["punteggio"] = (contrib.sum(axis=1) / tot).round(1)
    out.attrs = {**tab.attrs, "pesi": pesi, "metodo": "rango" if robusto else "min-max"}
    return out.sort_values("punteggio", ascending=False), contrib.round(1)


def delta_sharpe(prezzi, bench, n_boot=2000, seme=42):
    """Ogni ticker vs benchmark: la differenza di Sharpe e' distinguibile da zero?
    Bootstrap APPAIATO: ricampiona righe intere, cosi' la correlazione resta intatta.
    Limite: assume giorni indipendenti. L'intervallo vero e' piu' largo."""
    rng = np.random.default_rng(seme)
    r = prezzi.pct_change().dropna()
    n = len(r)
    sh = lambda s: s.mean() / s.std() * np.sqrt(GIORNI_BORSA)
    righe = []
    for t in r.columns:
        if t == bench:
            continue
        oss = sh(r[t]) - sh(r[bench])
        d = np.empty(n_boot)
        for i in range(n_boot):
            c = r.iloc[rng.integers(0, n, n)]
            d[i] = sh(c[t]) - sh(c[bench])
        lo, hi = np.percentile(d, [5, 95])
        righe.append({"ticker": t, "d_sharpe": round(oss, 3),
                      "ic90_lo": round(lo, 3), "ic90_hi": round(hi, 3),
                      "distinguibile": not (lo < 0 < hi)})
    tab = pd.DataFrame(righe).set_index("ticker")
    tab.attrs = {"bench": bench, "n_boot": n_boot, "giorni": n,
                 "metodo": "bootstrap appaiato su giorni singoli"}
    return tab
