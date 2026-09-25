from app.ingest import ConceptMatcher, chunk_markdown


def test_graph_built(store):
    st = store.stats()
    assert st["Document"] == 13 and st["Chunk"] > 30
    assert st["VERFIJNT"] >= 8           # werkinstructies verfijnen standaarddocs
    assert st["GERELATEERD_AAN"] > 0     # concept co-occurrence


def test_concept_matcher_synonyms_and_boundaries(cfg):
    m = ConceptMatcher(cfg["concepts"])
    assert "Barcode" in m.find("De scanner doet het niet")
    assert "Dubbele controle" in m.find("insuline toedienen")
    assert "Labaanvraag" not in m.find("laboratoriumachtig")  # geen match midden in een woord


def test_chunking_by_heading():
    body = "# T\n\n## A\ntekst a\n\n## B\ntekst b\n> disclaimer"
    assert chunk_markdown(body, 500) == [("A", "tekst a"), ("B", "tekst b")]


def test_refinement_expansion_crosses_sources(store):
    hits = store.refined_chunks(["std-med-toedienen"], limit=50)
    assert {"wi-dubbele-controle", "wi-barcodescanners"} <= {h["doc_id"] for h in hits}
