import zipfile

from starter.verticals.lease import abstract, contract

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PARAS = [
    "LR3. Parties to this lease",
    "Landlord",
    "[LANDLORD] (company number [COMPANY NUMBER])",
    "LR4. Property",
    "“Main Rent”",
    "the yearly rent of [AMOUNT IN WORDS] pounds (£[AMOUNT IN FIGURES]);",
    "“Permitted Use”",
    "the use of the Premises as offices;",
    "[BREAK CLAUSE",
    "The Tenant may end the Term on the Break Date by giving notice.",
]


def docx(path):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in PARAS)
    xml = f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    return path


def test_abstract_flags_placeholders_and_optional_clauses(tmp_path):
    got = abstract(docx(tmp_path / "lease.docx"))
    assert got["main_rent"]["placeholder"] is True
    assert got["main_rent"]["source"] == "definition “Main Rent”"
    assert got["permitted_use"]["placeholder"] is False
    assert got["break_clause"]["optional"] is True
    assert "Break Date" in got["break_clause"]["value"]
    assert got["parties"]["placeholder"] is True
    assert got["insurance"]["value"] is None


def test_contract_objects_are_office_findings(tmp_path):
    place, evidence, findings = contract(docx(tmp_path / "lease.docx"), "MCL-TEST")
    assert place.use == "office"
    by_field = {f.field: f for f in findings}
    assert by_field["main_rent"].verdict == "flag" and by_field["main_rent"].severity == "info"
    assert "placeholder" in by_field["main_rent"].reasoning
    assert by_field["insurance"].verdict == "unverifiable"
    rent = next(e for e in evidence if e.field == "main_rent")
    assert rent.agent == "lease" and "[AMOUNT IN WORDS]" in rent.doc_span
    assert rent.source_name == "Model Commercial Lease MCL-TEST"
