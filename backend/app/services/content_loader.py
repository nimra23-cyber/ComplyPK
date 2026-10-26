"""Loads and validates JSON content files (questionnaire, control mapping, demo).

The questionnaire, control mapping, and demo answers are kept in editable JSON
files rather than hard-coded or stored in the database (Req 1.1, 3.4, 7.4). This
loader reads and validates them, raising a typed :class:`ContentError` on any
problem so routers can translate it into an HTTP 500 without leaking stack
traces or returning partial data (Req 1.4, 1.5, 3.6, 7.5).

Validation is strict: the questionnaire must contain exactly 20 well-formed
questions across the six expected domains, and demo answers must cover every
question with a valid value.

Layering: this is a service and depends only on the standard library and the
content files; it has no upward dependency on routers (Req 12.2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Content files live alongside this package under ``app/data``.
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_QUESTIONS_FILE = _DATA_DIR / "questions.json"
_CONTROL_MAPPING_FILE = _DATA_DIR / "control_mapping.json"
_DEMO_FILE = _DATA_DIR / "demo.json"

# The questionnaire is a fixed size across six domains (Req 1.1, 1.2).
_EXPECTED_QUESTION_COUNT = 20
_EXPECTED_DOMAINS = {
    "Access Control",
    "Backup & Recovery",
    "Patching",
    "Incident Response",
    "Vendor Risk",
    "Data Protection",
}
_ALLOWED_ANSWERS = {"yes", "partial", "no"}


class ContentError(RuntimeError):
    """Raised when a content file is missing, unparseable, or invalid.

    The message is safe to surface as a generic error indication; it never
    includes stack traces or secret values (Req 1.4, 3.6, 7.5).
    """


@dataclass(frozen=True)
class Question:
    """A validated questionnaire item."""

    id: str
    domain: str
    text: str
    allowed_answers: tuple[str, ...]


@dataclass(frozen=True)
class ControlRefs:
    """ISO 27001 and NIST CSF references for a single question."""

    iso_27001: tuple[str, ...]
    nist_csf: tuple[str, ...]


@dataclass(frozen=True)
class DemoData:
    """A sample company profile plus one answer per question (Req 7.1)."""

    company: dict[str, Any]
    answers: dict[str, str]


def _read_json(path: Path, label: str) -> Any:
    """Read and parse a JSON file, raising :class:`ContentError` on failure."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ContentError(f"The {label} file could not be loaded.") from exc
    except OSError as exc:
        raise ContentError(f"The {label} file could not be loaded.") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContentError(f"The {label} file is invalid and could not be parsed.") from exc


def load_questions() -> list[Question]:
    """Load and validate the questionnaire (Req 1.1, 1.2, 1.3, 1.5).

    Returns:
        The list of exactly 20 validated questions.

    Raises:
        ContentError: If the file is missing, unparseable, or does not contain
            exactly 20 well-formed questions across the six domains.
    """
    data = _read_json(_QUESTIONS_FILE, "questionnaire")

    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise ContentError("The questionnaire data is invalid.")

    questions: list[Question] = []
    seen_ids: set[str] = set()

    for item in data["questions"]:
        if not isinstance(item, dict):
            raise ContentError("The questionnaire data is invalid.")

        qid = item.get("id")
        domain = item.get("domain")
        text = item.get("text")
        allowed = item.get("allowed_answers")

        if not isinstance(qid, str) or not qid:
            raise ContentError("The questionnaire data is invalid.")
        if qid in seen_ids:
            raise ContentError("The questionnaire data is invalid.")
        if not isinstance(domain, str) or domain not in _EXPECTED_DOMAINS:
            raise ContentError("The questionnaire data is invalid.")
        if not isinstance(text, str) or not text:
            raise ContentError("The questionnaire data is invalid.")
        if not isinstance(allowed, list) or set(allowed) != _ALLOWED_ANSWERS:
            raise ContentError("The questionnaire data is invalid.")

        seen_ids.add(qid)
        questions.append(
            Question(
                id=qid,
                domain=domain,
                text=text,
                allowed_answers=tuple(allowed),
            )
        )

    if len(questions) != _EXPECTED_QUESTION_COUNT:
        raise ContentError("The questionnaire data is invalid.")

    return questions


def load_control_mapping() -> dict[str, ControlRefs]:
    """Load the editable control mapping (Req 3.2, 3.4, 3.5).

    A question missing from the file, or a standard missing for a question,
    yields empty reference lists at the point of use; this loader simply parses
    whatever references are present.

    Raises:
        ContentError: If the file is missing or cannot be parsed (Req 3.6).
    """
    data = _read_json(_CONTROL_MAPPING_FILE, "control mapping")

    if not isinstance(data, dict):
        raise ContentError("The control mapping data is invalid.")

    mapping: dict[str, ControlRefs] = {}
    for qid, refs in data.items():
        if not isinstance(refs, dict):
            raise ContentError("The control mapping data is invalid.")
        iso = refs.get("iso_27001", [])
        nist = refs.get("nist_csf", [])
        if not isinstance(iso, list) or not isinstance(nist, list):
            raise ContentError("The control mapping data is invalid.")
        mapping[qid] = ControlRefs(
            iso_27001=tuple(str(x) for x in iso),
            nist_csf=tuple(str(x) for x in nist),
        )

    return mapping


def load_demo() -> DemoData:
    """Load and validate the demo-mode sample data (Req 7.1, 7.4, 7.5).

    The demo answers must cover every questionnaire question exactly once with a
    valid value.

    Raises:
        ContentError: If the file is missing, unparseable, or does not provide a
            valid answer for every question.
    """
    data = _read_json(_DEMO_FILE, "demo")

    if not isinstance(data, dict):
        raise ContentError("The demo data is invalid.")

    company = data.get("company")
    answers = data.get("answers")
    if not isinstance(company, dict) or not isinstance(answers, dict):
        raise ContentError("The demo data is invalid.")

    question_ids = {q.id for q in load_questions()}

    if set(answers.keys()) != question_ids:
        raise ContentError("The demo data is invalid.")
    for value in answers.values():
        if value not in _ALLOWED_ANSWERS:
            raise ContentError("The demo data is invalid.")

    return DemoData(company=company, answers=dict(answers))
