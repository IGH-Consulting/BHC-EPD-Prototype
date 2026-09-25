"""Chat-UI voor de EPD Expert Agent.

    streamlit run ui/streamlit_app.py
    EPD_STORE=memory EPD_EMBEDDING=hash EPD_LLM=fake streamlit run ui/streamlit_app.py   # demo zonder Docker
"""
import sys
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import build_agent  # noqa: E402
from app.config import load_config  # noqa: E402

st.set_page_config(page_title="EPD Expert Agent", page_icon="🩺", layout="wide")

CONF_BADGE = {"hoog": "🟢 hoog", "middel": "🟠 middel", "laag": "🔴 laag"}


@st.cache_resource(show_spinner="Agent en kennisgraaf laden…")
def get_agent():
    return build_agent(load_config())


try:
    agent = get_agent()
except Exception as e:  # meestal: Neo4j of Ollama draait niet
    st.error(f"Kan de agent niet starten: {e}")
    st.info("Draaien Neo4j en Ollama? `docker compose up -d` en daarna `python scripts/ingest.py`. "
            "Of start de demo-modus zonder Docker (zie README).")
    st.stop()

cfg = agent.cfg

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🩺 EPD Expert Agent")
    st.caption("Prototype · HiX · fictieve testbronnen")
    b = cfg["backends"]
    st.markdown(f"**Store:** `{b['store']}`  \n**LLM:** `{b['llm']}`"
                + (f" (`{cfg['ollama']['chat_model']}`)" if b["llm"] == "ollama" else "")
                + f"  \n**Embeddings:** `{b['embedding']}`"
                + (f" (`{cfg['ollama']['embed_model']}`)" if b["embedding"] == "ollama" else ""))
    try:
        st.markdown("**Kennisgraaf**")
        st.json(agent.store.stats(), expanded=False)
    except Exception as e:
        st.warning(f"Graaf niet bereikbaar: {e}")
    use_faq = st.toggle("FAQ-shortcut gebruiken", value=True,
                        help="Bijna identieke vraag al in de FAQ? Dan direct dat antwoord (scheelt een LLM-call).")
    st.markdown("**Voorbeeldvragen**")
    for q in ["Ik krijg 'Barcode niet herkend' bij het toedienen, wat nu?",
              "Voor welke middelen is een dubbele controle verplicht?",
              "Opname kan niet worden afgesloten: openstaande orders",
              "Een labaanvraag staat op verzendfout, opnieuw aanvragen?",
              "Wie doet de medicatieverificatie buiten kantoortijd?"]:
        if st.button(q, width="stretch"):
            st.session_state.pending = q


def graph_dot(r: dict) -> str:
    """Subgraaf van het antwoord: vraag → concepten → chunks → documenten → modules."""
    esc = lambda s: str(s).replace('"', "'")  # noqa: E731
    lines = ['digraph G { rankdir=LR; node [shape=box, style="rounded,filled", fontname=Helvetica, fontsize=10];',
             '"Q" [label="Vraag", fillcolor="#dbeafe"];']
    for c in r["concepts"] + r["related"][:2]:
        lines.append(f'"c:{esc(c)}" [label="{esc(c)}", shape=ellipse, fillcolor="#fef3c7"];')
        lines.append(f'"Q" -> "c:{esc(c)}" [style={"solid" if c in r["concepts"] else "dashed"}];')
    for s in r["sources"]:
        cid = f"k:{s['agent']}:{s['nr']}"
        color = "#dcfce7" if s["bron"] == "ziekenhuis" else "#f3f4f6"
        lines.append(f'"{cid}" [label="[{s["nr"]}] {esc(s["sectie"])[:40]}", fillcolor="{color}"];')
        lines.append(f'"d:{esc(s["titel"])}" [label="{esc(s["titel"])[:45]}", fillcolor="{color}", shape=note];')
        lines.append(f'"{cid}" -> "d:{esc(s["titel"])}" [label="DEEL_VAN", fontsize=8];')
        lines.append(f'"m:{esc(s["module"])}" [label="{esc(s["module"])}", fillcolor="#ede9fe", shape=folder];')
        lines.append(f'"d:{esc(s["titel"])}" -> "m:{esc(s["module"])}" [label="OVER_MODULE", fontsize=8];')
        for c in s["concepten"]:
            if c in r["concepts"] or c in r["related"][:2]:
                lines.append(f'"c:{esc(c)}" -> "{cid}" [label="NOEMT", fontsize=8, color="#b45309"];')
        if "vector" in s["via"]:
            lines.append(f'"Q" -> "{cid}" [color="#2563eb", style=dotted];')
    lines.append("}")
    return "\n".join(dict.fromkeys(lines))  # dubbele regels eruit


def render_result(r: dict) -> None:
    st.markdown(r["answer"])
    meta = f"Betrouwbaarheid: {CONF_BADGE[r['confidence']]} · {r['seconds']} s"
    if r["from_faq"]:
        meta += f" · ⚡ uit de FAQ (similarity {r['faq_similarity']})"
    else:
        meta += f" · route: {', '.join(r['modules'])}"
    st.caption(meta)
    if r.get("faq"):
        st.caption({"nieuw": "➕ Toegevoegd aan de FAQ", "bijgewerkt": "🔁 FAQ-item opnieuw gesteld (score +1)",
                    "genegeerd": "FAQ: niet opgenomen (kwaliteitspoort)"}[r["faq"]["actie"]])
    if r["from_faq"]:
        return
    with st.expander("🔍 Hoe kwam dit antwoord tot stand?"):
        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown(f"**Herkende concepten:** {', '.join(r['concepts']) or '—'}  \n"
                        f"**Gerelateerd (via graaf):** {', '.join(r['related'][:5]) or '—'}")
            st.markdown("**Routering**")
            st.dataframe(r["routes"], hide_index=True, width="stretch")
            if len(r["agents"]) > 1:
                st.markdown("**Deelantwoorden per agent**")
                for a in r["agents"]:
                    st.markdown(f"*{a['module']} ({a['werkgroep']})*")
                    st.markdown(a["answer"])
        with c2:
            st.graphviz_chart(graph_dot(r), width="stretch")
        st.markdown("**Bronnen**")
        for s in r["sources"]:
            tag = "🏥 ziekenhuis" if s["bron"] == "ziekenhuis" else "📘 standaard"
            st.markdown(f"**[{s['nr']}]** {tag} · {s['titel']} – *{s['sectie']}* · cos {s['cosine']} · via {', '.join(s['via'])}")
            st.caption(s["tekst"][:400] + ("…" if len(s["tekst"]) > 400 else ""))


tab_chat, tab_faq = st.tabs(["💬 Chat", "📈 Dynamische FAQ"])

# ---------------------------------------------------------------- chat
with tab_chat:
    st.session_state.setdefault("history", [])
    for msg in st.session_state.history:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                render_result(msg["content"])

    question = st.chat_input("Beschrijf je vraag, foutmelding of incident…")
    question = question or st.session_state.pop("pending", None)
    if question:
        st.session_state.history.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Agents raadplegen de kennisgraaf… (op CPU kan dit even duren)"):
                result = agent.ask(question, use_faq=use_faq)
            render_result(result)
        st.session_state.history.append({"role": "assistant", "content": result})

# ---------------------------------------------------------------- FAQ
with tab_faq:
    f = agent.faq
    st.markdown(
        f"Elke vergelijkbare vraag geeft **+1**; de score **halveert elke {cfg['faq']['half_life_days']} dagen** "
        f"zonder nieuwe vragen. Onder **{cfg['faq']['min_score_visible']}** verdwijnt een vraag uit de FAQ, "
        f"onder **{cfg['faq']['prune_below']}** wordt hij verwijderd. Alleen antwoorden met betrouwbaarheid "
        f"≥ *{cfg['faq']['min_confidence']}* komen erin."
    )
    days = st.slider("⏩ Simuleer tijd: spoel vooruit (dagen)", 0, 90, 0,
                     help="Laat zien hoe de FAQ eruitziet als er N dagen geen nieuwe vragen komen.")
    now = time.time() + days * 86400
    # Bij simuleren niet prunen: dat zou echte data verwijderen.
    items = f.top(now=now, include_hidden=True) if days == 0 else [
        {**it, "score": round(f.decayed(it["score"], time.time(), now), 3)}
        for it in f.top(include_hidden=True)
    ]
    for it in items:
        it["zichtbaar"] = it["score"] >= f.min_visible
    visible = [it for it in items if it["zichtbaar"]][: f.max_items]
    hidden = [it for it in items if not it["zichtbaar"]]
    if not items:
        st.info("Nog geen FAQ-items. Stel een paar vragen in de chat, of draai `python scripts/seed_faq.py`.")
    top_score = max([it["score"] for it in visible] + [1.0])
    for it in visible:
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"**{it['vraag']}**")
                st.progress(min(1.0, it["score"] / top_score),
                            text=f"score {it['score']} · {it['n_gesteld']}× gesteld · laatst {it['dagen_geleden'] + days:.0f} d geleden · "
                                 f"verdwijnt over ~{f.days_until_hidden(it['score']):.0f} d · {it['module'] or ''}")
                with st.expander("Antwoord"):
                    st.markdown(it["antwoord"])
                    if it["varianten"]:
                        st.caption("Ook gesteld als: " + " · ".join(it["varianten"]))
            with c2:
                if days == 0:
                    if st.button(f"👍 {it['likes']}", key=f"up{it['id']}"):
                        f.feedback(it["id"], True)
                        st.rerun()
                    if st.button(f"👎 {it['dislikes']}", key=f"down{it['id']}"):
                        f.feedback(it["id"], False)
                        st.rerun()
    if hidden:
        with st.expander(f"Weggezakt ({len(hidden)}) – niet meer zichtbaar in de FAQ"):
            for it in hidden:
                st.markdown(f"- {it['vraag']} · score {it['score']}")
