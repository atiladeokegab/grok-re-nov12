from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_every_source_file_is_under_1000_lines():
    files = [p for d in ("starter", "scripts", "tests") for p in (ROOT / d).rglob("*.py")]
    big = {
        str(p.relative_to(ROOT)): n for p in files if (n := len(p.read_text().splitlines())) >= 1000
    }
    assert big == {}
