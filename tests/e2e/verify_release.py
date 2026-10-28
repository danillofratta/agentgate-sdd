"""Verify release documentation references against an existing Pytest JUnit report."""

import argparse
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import unquote


def heading_ids(content: str) -> set[str]:
    counts: Counter[str] = Counter()
    result = set()
    for heading in re.findall(r"^#{1,6} (.+)$", content, re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        index = counts[slug]
        counts[slug] += 1
        result.add(slug if not index else f"{slug}-{index}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    matrix = (root / "docs/requirements_traceability.md").read_text(encoding="utf-8")
    specs = root / "openspec/changes/agentgate-core/specs"
    rows = re.findall(r"^\| (DH\d+|OA\d+|EC\d+) \| (.*?) \| (.*?) \|$", matrix, re.MULTILINE)
    expected = []
    for capability, prefix in (
        ("development-harness", "DH"),
        ("operation-authorization", "OA"),
        ("execution-control", "EC"),
    ):
        content = (specs / capability / "spec.md").read_text(encoding="utf-8")
        expected.extend(
            (f"{prefix}{index:02}", title)
            for index, title in enumerate(
                re.findall(r"^#### Scenario: (.+)$", content, re.MULTILINE), 1
            )
        )
    assert Counter((label, title) for label, title, _ in rows) == Counter(expected), (
        "Scenario rows differ from active specs"
    )
    tests = list(ET.parse(args.junit).iter("testcase"))
    assert tests and all(
        not any(test.find(tag) is not None for tag in ("failure", "error", "skipped"))
        for test in tests
    ), "Report must contain only passing tests"
    passed = {
        test.attrib["classname"].replace(".", "/") + ".py::" + test.attrib["name"] for test in tests
    }
    references = set(re.findall(r"`(tests/[^`]+::[^`]+)`", matrix))
    assert references, "No test references"
    assert not references - passed, f"Missing passing nodes: {sorted(references - passed)}"
    definitions = set(re.findall(r"\*\*(D\d+) —", matrix))
    used = set()
    for label, _, evidence in rows:
        checks = set(re.findall(r"\bD\d+\b", evidence))
        nodes = re.findall(r"`(tests/[^`]+::[^`]+)`", evidence)
        assert nodes or checks, f"No evidence: {label}"
        used.update(checks)
    assert used == definitions, "Missing or unused documentation checks"
    links = 0
    for path in [root / "README.md", *sorted((root / "docs").glob("*.md"))]:
        content = path.read_text(encoding="utf-8")
        for target in re.findall(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)", content):
            if "://" in target or target.startswith("mailto:"):
                continue
            relative, _, anchor = unquote(target).partition("#")
            destination = (path.parent / relative).resolve() if relative else path
            assert destination.exists(), f"Missing link in {path.name}: {target}"
            if anchor:
                assert destination.is_file() and anchor in heading_ids(
                    destination.read_text(encoding="utf-8")
                ), f"Missing heading in {path.name}: {target}"
            links += 1
    print(
        f"Verified {len(rows)} scenarios, {len(references)} exact passing nodes, "
        f"{len(definitions)} documentation-check definitions and {links} relative links."
    )
    print("Prose check execution and semantic coverage require the documented review.")


if __name__ == "__main__":
    main()
