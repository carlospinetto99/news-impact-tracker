import os, base64
import pandas as pd
import streamlit as st

BLU, VERDE, GRIGIO = "#3B3FB6", "#008923", "#B0AAAB"
VERDE_SU, ROSSO_GIU = "#00BB31", "#FF3B3B"

st.set_page_config(page_title="News Impact Tracker", layout="centered")

@st.cache_data(ttl=600)
def carica():
    EV = pd.read_csv("eventi.csv")
    EV["rumore"] = EV["rumore"].map({True:True, False:False, "True":True, "False":False})
    if "tipo" not in EV.columns:  EV["tipo"] = "stock"
    if "bench" not in EV.columns: EV["bench"] = "market"
    return EV, pd.read_csv("notizie.csv")

@st.cache_data
def img64(p):
    with open(p, "rb") as f: return base64.b64encode(f.read()).decode()

EV, NZ = carica()

c1, c2 = st.columns(2)
mondo = c1.radio("w", ["General", "ESG"], horizontal=True, label_visibility="collapsed")
tipo  = c2.radio("t", ["Stocks", "ETFs"], horizontal=True, label_visibility="collapsed")
c3, c4 = st.columns([1.4, 1])
ordine = c3.selectbox("s", ["Newest first", "Most significant", "Out of noise only"],
                      label_visibility="collapsed")
banda = c4.checkbox("noise band", value=True)
FONDO = BLU if mondo == "General" else VERDE

st.markdown(f"""<style>
 .stApp {{ background:{FONDO}; }}
 html, body, [class*="css"], .stMarkdown, p, div, span {{ font-family: Arial, Helvetica, sans-serif !important; }}
 .card {{ background:#fff; border-radius:10px; padding:20px 22px; margin-bottom:16px; }}
 .tag {{ display:inline-block; background:{FONDO}; color:#fff; font-size:11px;
         padding:3px 9px; border-radius:3px; letter-spacing:.6px; font-weight:bold; }}
 .meta {{ color:#888; font-size:12px; }}
 .tit {{ font-size:16px; font-weight:bold; color:#111; margin:10px 0 3px 0; line-height:1.35; }}
 .fatto {{ font-size:13px; color:#333; margin-top:12px; border-top:1px solid #eee; padding-top:10px; }}
 .card a {{ color:{FONDO}; }}
 h1 {{ color:#fff !important; }}
 .disc {{ color:#fff; font-size:13px; opacity:.85; }}
 .vuoto {{ background:#fff; border-radius:10px; padding:26px 22px; color:#555; font-size:14px; }}
</style>""", unsafe_allow_html=True)

st.markdown("# News Impact Tracker")
st.markdown('<div class="disc" style="margin-bottom:18px">Not a recommendation. '
            'Shows what happened, not what will.</div>', unsafe_allow_html=True)

vis = EV[(EV["mondo"] == mondo) & (EV["tipo"] == ("etf" if tipo == "ETFs" else "stock"))].copy()

if not len(vis):
    st.markdown('<div class="vuoto"><b>No ETF events yet.</b><br><br>ETF cards are derived, '
                'not scraped: when a news moves a company, the tracker computes the mechanical '
                'effect on every ETF holding it (weight × abnormal return) and compares it to '
                'the ETF\'s actual move. Coming next.</div>', unsafe_allow_html=True)
    st.stop()

if ordine == "Most significant":
    vis["sig"] = (vis["car"].abs() / vis["soglia"]).fillna(-1)
    vis = vis.sort_values("sig", ascending=False)
elif ordine == "Out of noise only":
    vis = vis[vis["rumore"] == False].sort_values("giorno0", ascending=False)
else:
    vis = vis.sort_values("giorno0", ascending=False)

st.caption(f"{len(vis)} events · {int((vis['stato']=='closed').sum())} with a number")

for _, e in vis.head(25).iterrows():
    art = NZ[NZ["evento"] == e["evento"]]
    tg = e["tag"] if isinstance(e.get("tag"), str) and e["tag"] else ""
    et = mondo + (f" · {tg}" if tg else "")
    if e.get("materiale") == True:    et += " · material"
    elif e.get("materiale") == False: et += " · not material"

    h = f'<div class="card"><span class="tag">{et}</span>'
    h += f'<span class="meta">&nbsp;&nbsp;{e["giorno0"]} · {len(art)} ' \
         f'{"story" if len(art)==1 else "stories"}</span>'
    for _, a in art.head(2).iterrows():
        h += f'<div class="tit">{a["titolo"]}</div>' \
             f'<span class="meta">{a["fonte"]} · ' \
             f'<a href="{a["link"]}" target="_blank">read source ↗</a></span>'

    if e["stato"] != "closed":
        nota = {"waiting":"market hasn\'t opened yet",
                "consolidating":"window closes in a few days",
                "no data":"no price data"}.get(e["stato"], e["stato"])
        h += f'<div class="fatto"><b>{e["ticker"]}</b> · ' \
             f'<span style="color:{GRIGIO}">measuring — {nota}</span></div>'
    else:
        col = GRIGIO if e["rumore"] else (VERDE_SU if e["car"] > 0 else ROSSO_GIU)
        nota = " · within noise" if e["rumore"] else ""
        h += f'<div class="fatto"><b>{e["ticker"]}</b> · ' \
             f'<span style="color:{col};font-weight:bold">{e["car"]:+.2f}%</span> ' \
             f'vs <b>{e["bench"]}</b> · window [-1,+3]{nota} ' \
             f'<span class="meta">(noise ±{e["soglia"]:.2f}%)</span></div>'
        base = e["evento"].replace("|","_").replace("^","I")
        p = f'grafici/{base}.png' if banda else f'grafici/{base}_nb.png'
        if not os.path.exists(p): p = f'grafici/{base}.png'
        if os.path.exists(p):
            h += f'<img src="data:image/png;base64,{img64(p)}" ' \
                 f'style="width:100%;border-radius:6px;margin-top:12px">'
    h += '</div>'
    st.markdown(h, unsafe_allow_html=True)

st.markdown('<div class="disc" style="margin-top:26px">Measures financial materiality only '
            '(outside-in): how the market repriced the company. It cannot measure a company\'s '
            'impact on the world. Materiality approximated from SASB via GICS sectors. '
            'Not financial advice.</div>', unsafe_allow_html=True)
