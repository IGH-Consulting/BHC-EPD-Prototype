# BHC EPD Expert Agent – prototype

Lokaal prototype van een **EPD Expert Agent** voor HiX: een GraphRAG-kennisbank met standaarddocumentatie
en ziekenhuisspecifieke werkinstructies, **agent-orkestratie per module/werkgroep**, een chat-UI en een
**dynamische FAQ**. Alles draait lokaal met gratis modellen, ook op een laptop zonder GPU.

> ⚠️ De testbronnen in `data/` zijn **fictief** (inclusief "Ziekenhuis Voorbeeldstad"). Het is geen officiële
> ChipSoft-documentatie. Ze zijn bedoeld om de werking te laten zien.

## Architectuur

```
            ┌──────────── Ingestie (scripts/ingest.py) ────────────┐
 data/standaard/*.md ─┐                                             │
 data/ziekenhuis/*.md ┴─► chunk per sectie ─► embeddings (bge-m3) ──┼─► Neo4j kennisgraaf
                          + concepten (begrippenlijst, opt. LLM)    │
                          + VERFIJNT-relaties uit metadata          │
            └───────────────────────────────────────────────────────┘

 Vraag ─► [analyse] ─► [router] ─┬─► [agent Medicatie]            ─┐
          embedding    modules   ├─► [agent Patiëntlogistiek]      ├─► [synthese] ─► antwoord + bronnen
          concepten    kiezen    ├─► [agent Orders & Uitslagen]    │   betrouwbaarheid, escalatie
                                 └─► [agent Verpleegkundig dossier]┘        │
                                    (parallel, LangGraph Send)              ▼
                                                                   Dynamische FAQ (SQLite)
```

**Kennisgraaf (Neo4j)**

```
(:Bron)<-[:UIT_BRON]-(:Document)-[:OVER_MODULE]->(:Module)-[:BEHEERD_DOOR]->(:Werkgroep)
                        │   ▲
               DEEL_VAN │   │ VERFIJNT      (werkinstructie verfijnt standaarddoc)
                        ▼   │
(:Chunk)-[:VOLGT_OP]->(:Chunk)-[:NOEMT]->(:Concept)-[:HOORT_BIJ]->(:Module)
                                           (:Concept)-[:GERELATEERD_AAN]-(:Concept)
```

**Hybride GraphRAG-retrieval** (`app/retrieval.py`): vector search binnen de module van de agent,
aangevuld met (1) chunks die dezelfde HiX-concepten noemen, (2) de lokale werkinstructie die een gevonden
standaarddoc *verfijnt* (ook over modulegrenzen heen), en (3) gerelateerde concepten via co-occurrence.
Ziekenhuisspecifieke kennis krijgt een kleine voorrangsbonus.

**Waarom geen volledige LLM-graph-extractie à la Microsoft GraphRAG?** Op CPU met een 3B-model is dat traag
en onbetrouwbaar. De graaf komt daarom uit wat we zeker weten (structuur, metadata, begrippenlijst). LLM-extractie
is optioneel (`--llm-concepts`). Met een GPU of groter model kun je die stap uitbreiden.

**Dynamische FAQ** (`app/faq.py`): elke vraag met een voldoende betrouwbaar antwoord komt in de FAQ.
Vergelijkbare vragen worden samengevoegd (embedding-similarity) en tellen **+1** op. De score **halveert elke
14 dagen** zonder nieuwe vragen:

```
score(t) = score(t0) · 0.5^((t − t0) / halfwaardetijd)
```

Vaak en recent gesteld = bovenaan. Onder `min_score_visible` verdwijnt een vraag uit beeld, onder `prune_below`
wordt hij verwijderd. 👍 geeft +0.5, 👎 geeft −1. Bijna identieke vragen worden direct uit de FAQ beantwoord
(scheelt een LLM-call). Alle parameters staan in `config.yaml`.

## Snel starten

### Optie A – volledig (Neo4j + Ollama in Docker)

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

docker compose up -d
docker compose exec ollama ollama pull qwen2.5:3b       # ~2 GB, chatmodel
docker compose exec ollama ollama pull bge-m3           # ~1.2 GB, meertalige embeddings

python scripts/ingest.py                                 # bronnen -> kennisgraaf
python scripts/evaluate.py                               # routering, hit@k en drempelkalibratie
streamlit run ui/streamlit_app.py                        # chat op http://localhost:8501
```

Neo4j Browser: http://localhost:7474 (neo4j / epdexpert123). Probeer bijvoorbeeld:

```cypher
MATCH p=(w:Document {bron:'ziekenhuis'})-[:VERFIJNT]->(:Document) RETURN p
MATCH p=(:Concept {naam:'Barcode'})<-[:NOEMT]-(:Chunk)-[:DEEL_VAN]->(:Document) RETURN p
```

Heb je Ollama al native geïnstalleerd? Laat dan de `ollama`-service in `docker-compose.yml` weg en draai
`ollama pull …` lokaal.

### Optie B – demo-modus zonder Docker en zonder modellen

Handig om de flow te laten zien of te ontwikkelen. Hierin gebruikt de agent een in-memory graaf,
lexicale embeddings en een extractief "antwoord" in plaats van een LLM.

```bash
pip install -r requirements.txt
python scripts/ingest.py --demo
# macOS/Linux:
EPD_STORE=memory EPD_EMBEDDING=hash EPD_LLM=fake streamlit run ui/streamlit_app.py
# Windows PowerShell:
$env:EPD_STORE="memory"; $env:EPD_EMBEDDING="hash"; $env:EPD_LLM="fake"; streamlit run ui/streamlit_app.py
```

### Overige commando's

```bash
python scripts/ask.py "Barcode niet herkend bij toedienen, wat nu?"   # vraag via CLI
python scripts/seed_faq.py        # gesimuleerde vraaghistorie (60 dagen) om het FAQ-verval te tonen
pytest -q                         # tests (draaien in demo-modus, geen Docker nodig)
```

## Eigen bronnen toevoegen

Zet markdown-bestanden in `data/standaard/` of `data/ziekenhuis/` met front matter:

```yaml
---
id: wi-mijn-instructie
titel: Werkinstructie ...
bron: ziekenhuis              # standaard | ziekenhuis
type: werkinstructie          # handleiding | werkinstructie | opleiding | release_notes
module: Medicatie             # moet bestaan in config.yaml -> modules
organisatie: Ziekenhuis X
versie: "2025.1"
verfijnt: [std-med-toedienen] # optioneel: welke standaarddocs dit document verfijnt
---
```

Nieuwe module of werkgroep? Voeg die toe onder `modules:` in `config.yaml`; er komt automatisch een agent
voor. Begrippen en synoniemen staan onder `concepts:`. Draai daarna opnieuw `python scripts/ingest.py`.
Voor PDF/Word: converteer eerst naar markdown (bijvoorbeeld met `markitdown` of `pandoc`).

## Prestaties op CPU

Met `qwen2.5:3b` kost een antwoord op een gemiddelde laptop ongeveer **20–60 s** per agent. Een vraag die twee
modules raakt, doet 3 LLM-calls (2 agents + synthese). Knoppen om aan te draaien:
`orchestration.max_agents: 1`, `ollama.chat_model: qwen2.5:1.5b`, of de FAQ-shortcut (direct antwoord).

## Bekende beperkingen / volgende stappen

- **Drempels** voor betrouwbaarheid en FAQ-dubbelingen zijn ingeschat voor `bge-m3`. Kalibreer ze met
  `scripts/evaluate.py` op je eigen bronnen.
- De Neo4j-backend is geschreven voor Neo4j 5 (vector index), maar niet in de ontwikkelomgeving getest; de
  logica is getest via de in-memory backend met dezelfde interface. Loop bij problemen eerst `scripts/ingest.py` na.
- Router is deterministisch (concepten + similarity); een LLM-router is een logische uitbreiding bij een groter model.
- Nog niet in scope: community-escalatie (alleen een hook bij lage betrouwbaarheid), Topdesk-koppeling,
  multi-tenant scheiding per organisatie, anonimisering, authenticatie.

## Structuur

```
app/
  config.py        config.yaml laden (+ env-overrides EPD_STORE / EPD_LLM / EPD_EMBEDDING)
  llm.py           Ollama-clients + offline fallbacks (HashEmbedder, FakeChat)
  graph_store.py   Neo4jStore en MemoryStore (zelfde interface)
  ingest.py        parsing, chunking, concepten, graaf opbouwen
  retrieval.py     hybride GraphRAG-retrieval
  agents.py        LangGraph-orkestratie: analyse -> router -> module-agents -> synthese
  faq.py           dynamische FAQ met exponentieel verval
ui/streamlit_app.py  chat, uitleg (route, graaf, bronnen), FAQ met tijdsimulatie
scripts/           ingest, ask, evaluate, seed_faq
data/              fictieve testbronnen + gouden evaluatieset
tests/             pytest (demo-backends)
```
