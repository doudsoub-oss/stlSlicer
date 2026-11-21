"""Docs drift tests (PLAN.md §8.5): fail when the code and the docs disagree."""

import json
import re
import tomllib
from pathlib import Path

from stlsplit import cli, config
from stlsplit.config import Config
from stlsplit.errors import DIAGNOSTIC_CODES, ExitCode

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_tables(text: str) -> list[list[dict[str, str]]]:
    """Return every pipe table as a list of rows, each a mapping header -> cell."""
    lines = text.splitlines()
    tables: list[list[dict[str, str]]] = []
    i = 0
    while i < len(lines):
        is_header = lines[i].startswith("|") and i + 1 < len(lines)
        if is_header and re.fullmatch(r"\|[-:| ]+\|", lines[i + 1].strip()):
            header = cells(lines[i])
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(dict(zip(header, cells(lines[i]), strict=True)))
                i += 1
            tables.append(rows)
        else:
            i += 1
    return tables


def configuration_rows() -> list[dict[str, str]]:
    text = read(DOCS / "CONFIGURATION.md")
    return [row for table in markdown_tables(text) for row in table if "TOML key" in row]


def documented_defaults() -> dict[str, str]:
    """Map each documented TOML key to the text of its Default cell."""
    defaults: dict[str, str] = {}
    for row in configuration_rows():
        match = re.fullmatch(r"`([a-z_]+\.[a-z_]+)`", row["TOML key"])
        if match:
            key = match[1]
            assert key not in defaults, f"{key} is documented twice"
            defaults[key] = row["Default"]
    return defaults


def parser_flags() -> set[str]:
    parser = cli.build_parser()
    return {flag for action in parser._actions for flag in action.option_strings}


# --- configuration ---------------------------------------------------------------------------


def test_every_config_key_has_exactly_one_row_in_configuration_md() -> None:
    assert sorted(documented_defaults()) == sorted(config.keys())


def test_documented_defaults_match_the_code() -> None:
    defaults = Config()
    for key, cell in documented_defaults().items():
        match = re.fullmatch(r"`(.+)`", cell)
        assert match, f"{key}: the default must be a TOML value in backticks, got {cell!r}"
        value = tomllib.loads(f"v = {match[1]}")["v"]
        documented = config.lookup(config.with_overrides(defaults, {key: value}, "docs"), key)
        assert documented == config.lookup(defaults, key), key


def test_every_cli_flag_appears_in_configuration_md() -> None:
    text = read(DOCS / "CONFIGURATION.md")
    missing = [f for f in sorted(parser_flags()) if not re.search(f"`{re.escape(f)}[` ]", text)]
    assert missing == []


def test_every_flag_in_the_cli_column_exists() -> None:
    known = parser_flags()
    documented = {
        flag
        for row in configuration_rows()
        if "CLI" in row
        for flag in re.findall(r"(?<![\w-])(--?[a-z][a-z-]*)", row["CLI"])
    }
    assert sorted(documented - known) == []


# --- exit and diagnostic codes ---------------------------------------------------------------


def test_every_exit_code_has_a_troubleshooting_heading() -> None:
    text = read(DOCS / "TROUBLESHOOTING.md")
    headings = re.findall(r"^### (\d+) — ", text, flags=re.MULTILINE)
    assert headings == [str(int(code)) for code in ExitCode]


def test_every_diagnostic_code_has_a_troubleshooting_heading_with_its_severity() -> None:
    text = read(DOCS / "TROUBLESHOOTING.md")
    headings = re.findall(
        r"^### (W\d{3}) — .*\((info|warning|partial)(?:, retired)?\)$", text, flags=re.MULTILINE
    )
    assert headings == [(entry.code, entry.severity) for entry in DIAGNOSTIC_CODES]


def test_troubleshooting_diagnostics_table_matches_the_registry() -> None:
    text = read(DOCS / "TROUBLESHOOTING.md")
    rows = [row for table in markdown_tables(text) for row in table if "Code" in row]
    assert [(row["Code"], row["Severity"]) for row in rows] == [
        (entry.code, entry.severity) for entry in DIAGNOSTIC_CODES
    ]


# --- ADR index and module map ----------------------------------------------------------------


def test_every_adr_is_indexed_and_every_indexed_adr_exists() -> None:
    adr_dir = DOCS / "adr"
    files = sorted(p.name for p in adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    linked = sorted(set(re.findall(r"\]\((\d{4}-[^)]+\.md)\)", read(adr_dir / "README.md"))))
    template = "0000-template.md"
    assert [f for f in linked if f != template] == [f for f in files if f != template]


def test_every_module_is_named_in_architecture_md() -> None:
    text = read(DOCS / "ARCHITECTURE.md")
    modules = sorted(p.stem for p in (ROOT / "src" / "stlsplit").glob("*.py"))
    assert [m for m in modules if f"`{m}`" not in text] == []


# --- output format ---------------------------------------------------------------------------


def test_every_top_level_schema_property_is_in_output_format_md() -> None:
    schema = json.loads(read(ROOT / "src" / "stlsplit" / "schemas" / "assembly.schema.json"))
    text = read(DOCS / "OUTPUT_FORMAT.md")
    assert schema["properties"]
    assert [name for name in schema["properties"] if f"`{name}`" not in text] == []
