import hashlib
from dataclasses import FrozenInstanceError, replace

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def synthetic_pdf(tmp_path, pages, filename="demo-policy.pdf"):
    """Write fictional text with the already-required pypdf; no extra generator."""
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Courier"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        commands = ["BT", "/F1 10 Tf", "14 TL", "40 750 Td"]
        for line in text.splitlines():
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.extend([f"({escaped}) Tj", "T*"])
        commands.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("cp1252"))
        page.replace_contents(stream)
    path = tmp_path / filename
    with path.open("wb") as stream:
        writer.write(stream)
    return path


def sample_corpus():
    from emporio_support_agent.policies import PolicyCorpus, PolicyPage, PolicySection, PolicySource

    sections = (
        PolicySection("1", "Demo information", "Body mentions PIX and delivery.", 1, 1),
        PolicySection("2", "PIX", "PIX requires all demo conditions, including condition B.", 2, 2),
        PolicySection("3", "Promoção", "Demo promotion has condition C and an exception.", 3, 4),
        PolicySection("4", "Contato WhatsApp", "Demo contact channel A.", 4, 4),
        PolicySection("5", "Contato WhatsApp", "Demo contact channel B; retain both sources.", 5, 5),
    )
    return PolicyCorpus(PolicySource("demo.pdf", "a" * 64, "9.3"), (PolicyPage(1, "Demo text"),), sections)


def test_loads_pdf_pages_hash_version_and_numbered_sections(tmp_path):
    from emporio_support_agent.policies import load_policy_pdf

    path = synthetic_pdf(tmp_path, (
        "Demo Header\nVersion 9.3\n1. Demo Payments\nGeneral condition.\n"
        "1.1 Demo Credit\nCredit condition.\n1.2 Demo Shipping\nFirst delivery condition.\nPage 1",
        "Demo Header\nSecond delivery condition.\n    1. Demo workflow step.\n"
        "    2. Demo workflow continuation.\n2. Demo Returns\nReturn condition.\nPage 2",
    ), filename="política-demo.pdf")
    corpus = load_policy_pdf(path)
    assert corpus.source.filename == "política-demo.pdf"
    assert corpus.source.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert corpus.source.version == "9.3"
    assert tuple(page.page_number for page in corpus.pages) == (1, 2)
    assert "Version 9.3" in corpus.pages[0].text
    assert tuple(s.section_id for s in corpus.sections) == ("1", "1.1", "1.2", "2")
    shipping = corpus.sections[2]
    assert shipping.title == "Demo Shipping"
    assert (shipping.page_start, shipping.page_end) == (1, 2)
    assert "First delivery condition." in shipping.text
    assert "Second delivery condition." in shipping.text
    assert "1. Demo workflow step." in shipping.text
    assert "2. Demo Returns" not in shipping.text
    assert "Demo Header" not in shipping.text and "Page 1" not in shipping.text
    assert "Credit condition." in corpus.sections[0].text
    assert "Second delivery condition." in corpus.sections[0].text
    assert "Return condition." not in corpus.sections[0].text
    assert "Return condition." in corpus.sections[3].text


def test_page_change_alone_does_not_close_a_section_and_blank_pages_keep_numbers(tmp_path):
    from emporio_support_agent.policies import load_policy_pdf

    path = synthetic_pdf(tmp_path, (
        "Version 4.2\n1. Demo Shipping\nCondition starts here.", "", "Condition ends here.",
    ))
    corpus = load_policy_pdf(path)
    assert tuple(p.page_number for p in corpus.pages) == (1, 2, 3)
    assert not corpus.pages[1].text.strip()
    assert len(corpus.sections) == 1
    assert (corpus.sections[0].page_start, corpus.sections[0].page_end) == (1, 3)
    assert "Condition ends here." in corpus.sections[0].text


def test_peer_heading_closes_previous_section_without_wrong_next_page_attribution(tmp_path):
    from emporio_support_agent.policies import load_policy_pdf

    path = synthetic_pdf(tmp_path, (
        "Demo Header\nVersion 4.2\n1. Demo First\nOnly first rule.\nPage 1",
        "Demo Header\n2. Demo Second\nOnly second rule.\nPage 2",
    ))
    corpus = load_policy_pdf(path)
    assert (corpus.sections[0].page_start, corpus.sections[0].page_end) == (1, 1)
    assert (corpus.sections[1].page_start, corpus.sections[1].page_end) == (2, 2)
    assert "second" not in corpus.sections[0].text.lower()


def test_running_header_removal_does_not_erase_identical_text_inside_a_rule(tmp_path):
    from emporio_support_agent.policies import load_policy_pdf

    path = synthetic_pdf(tmp_path, (
        "Demo Header\nVersion 1.0\n1. Demo Rule\nDemo Header\nFirst condition.",
        "Demo Header\nRemaining condition.",
    ))
    section = load_policy_pdf(path).sections[0]
    assert section.text.count("Demo Header") == 1
    assert "Remaining condition." in section.text


def test_invalid_filesystem_path_uses_policy_load_error(tmp_path):
    from emporio_support_agent.policies import PolicyLoadError, load_policy_pdf

    with pytest.raises(PolicyLoadError, match="read"):
        load_policy_pdf(tmp_path / "invalid\x00.pdf")


def test_nested_subsections_are_retained_inside_complete_parent_sections(tmp_path):
    from emporio_support_agent.policies import load_policy_pdf

    path = synthetic_pdf(tmp_path, ("Version 3.1\n1. Demo Parent\n1.1 Demo Child\n1.1.1 Demo Detail\nAll conditions.\n2. Next\nOther rule.",))
    sections = load_policy_pdf(path).sections
    assert tuple(s.section_id for s in sections) == ("1", "1.1", "1.1.1", "2")
    assert all("All conditions." in s.text for s in sections[:3])
    assert all("Other rule." not in s.text for s in sections[:3])


@pytest.mark.parametrize("text,problem", [
    ("1. Demo Payments\nA rule without version metadata.", "version"),
    ("Version 1.0\nVersion 2.0\n1. Demo\nA rule.", "version"),
    ("Version 1.0\nNo numbered policy structure.", "section"),
    ("Version 1.0\n1.1 Orphan Child\nA rule.", "section"),
    ("Version 1.0\n1. First\nA rule.\n1. Duplicate\nAnother rule.", "section"),
])
def test_missing_or_ambiguous_metadata_and_structure_fail(tmp_path, text, problem):
    from emporio_support_agent.policies import PolicyLoadError, load_policy_pdf

    with pytest.raises(PolicyLoadError, match=problem):
        load_policy_pdf(synthetic_pdf(tmp_path, (text,)))


def test_empty_extraction_fails(tmp_path):
    from emporio_support_agent.policies import PolicyLoadError, load_policy_pdf

    with pytest.raises(PolicyLoadError, match="text"):
        load_policy_pdf(synthetic_pdf(tmp_path, ("",)))


def test_missing_corrupt_and_directory_sources_fail_consistently(tmp_path):
    from emporio_support_agent.policies import PolicyLoadError, load_policy_pdf

    with pytest.raises(PolicyLoadError, match="read"):
        load_policy_pdf(tmp_path / "missing.pdf")
    with pytest.raises(PolicyLoadError, match="read"):
        load_policy_pdf(tmp_path)
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nnot a readable PDF")
    with pytest.raises(PolicyLoadError, match="PDF"):
        load_policy_pdf(corrupt)


def test_changing_source_bytes_rebuilds_hash_version_and_sections(tmp_path):
    from emporio_support_agent.policies import load_policy_pdf

    path = synthetic_pdf(tmp_path, ("Version 1.0\n1. Demo First\nFirst condition.",))
    first = load_policy_pdf(path)
    synthetic_pdf(tmp_path, ("Version 2.0\n1. Demo Changed\nNew condition.",))
    second = load_policy_pdf(path)
    assert first.source.sha256 != second.source.sha256
    assert second.source.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert second.source.version == "2.0"
    assert second.sections[0].title == "Demo Changed"


def test_policy_models_are_frozen():
    corpus = sample_corpus()
    with pytest.raises(FrozenInstanceError):
        corpus.source.version = "invented"
    with pytest.raises(FrozenInstanceError):
        corpus.pages[0].page_number = 99
    with pytest.raises(FrozenInstanceError):
        corpus.sections[0].text = "changed"
    with pytest.raises(FrozenInstanceError):
        corpus.sections = ()


def test_retrieval_weights_titles_and_returns_complete_original_sections():
    from emporio_support_agent.policies import search_policy_sections

    corpus = sample_corpus()
    result = search_policy_sections(corpus, "pix")
    assert tuple(s.section_id for s in result) == ("2", "1")
    assert result[0] is corpus.sections[1]
    assert "condition B" in result[0].text


def test_distinct_terms_not_repetition_control_ranking():
    from emporio_support_agent.policies import search_policy_sections

    corpus = sample_corpus()
    assert search_policy_sections(corpus, "pix pix pix delivery") == search_policy_sections(corpus, "pix delivery")


def test_multiple_relevant_sources_are_preserved_with_stable_ties_and_limit():
    from emporio_support_agent.policies import search_policy_sections

    corpus = sample_corpus()
    assert tuple(s.section_id for s in search_policy_sections(corpus, "whatsapp contato")) == ("4", "5")
    assert tuple(s.section_id for s in search_policy_sections(corpus, "whatsapp contato", limit=1)) == ("4",)
    assert search_policy_sections(corpus, "whatsapp contato") == search_policy_sections(corpus, "whatsapp contato")


@pytest.mark.parametrize("query", ["PROMOCAO", "promoção", "Promoção!!!"])
def test_case_accent_and_punctuation_normalization(query):
    from emporio_support_agent.policies import search_policy_sections

    assert tuple(s.section_id for s in search_policy_sections(sample_corpus(), query)) == ("3",)


@pytest.mark.parametrize("query", ["unrelated holographic waffles", "...!!!", "de e a"])
def test_no_meaningful_match_returns_empty_tuple(query):
    from emporio_support_agent.policies import search_policy_sections

    assert search_policy_sections(sample_corpus(), query) == ()


@pytest.mark.parametrize("query", ["", "   \n\t", None, 123, True])
def test_invalid_queries_fail(query):
    from emporio_support_agent.policies import search_policy_sections

    with pytest.raises(ValueError, match="query"):
        search_policy_sections(sample_corpus(), query)


@pytest.mark.parametrize("limit", [0, -1, True, 1.0, "3", None])
def test_invalid_limits_fail(limit):
    from emporio_support_agent.policies import search_policy_sections

    with pytest.raises(ValueError, match="limit"):
        search_policy_sections(sample_corpus(), "pix", limit=limit)


def test_provenance_contains_source_version_hash_section_and_page_range():
    from emporio_support_agent.policies import policy_section_provenance

    corpus = sample_corpus()
    result = policy_section_provenance(corpus, corpus.sections[2])
    for value in ("demo.pdf", "9.3", "a" * 64, "section=3", "pages=3-4"):
        assert value in result
    assert "pages=2" in policy_section_provenance(corpus, corpus.sections[1])
    with pytest.raises(ValueError, match="corpus"):
        policy_section_provenance(corpus, replace(corpus.sections[0], section_id="99"))
