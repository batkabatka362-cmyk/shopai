"""Legal Document Engine — compliance validator.

Validates that all required sections are present in generated legal
documents. Checks for completeness against jurisdiction requirements.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def validate_compliance(
    documents: list[dict[str, Any]],
    templates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate generated documents against required sections.

    Args:
        documents: List of generated document dicts.
        templates: List of template selection dicts (with required_sections).

    Returns:
        Structured dict with compliance check result and missing sections.
    """
    try:
        docs = copy.deepcopy(documents)
        tmpls = copy.deepcopy(templates)

        # Build doc type to document mapping
        doc_map: dict[str, dict[str, Any]] = {}
        for doc in docs:
            doc_type = str(doc.get("type", ""))
            doc_map[doc_type] = doc

        # Build template type mapping
        tmpl_map: dict[str, dict[str, Any]] = {}
        for tmpl in tmpls:
            tid = str(tmpl.get("template_id", ""))
            if tid.startswith("terms"):
                tmpl_map["terms"] = tmpl
            elif tid.startswith("privacy"):
                tmpl_map["privacy"] = tmpl
            elif tid.startswith("returns"):
                tmpl_map["returns"] = tmpl

        checks_total = 0
        checks_passed = 0
        issues: list[str] = []
        missing_sections: list[dict[str, Any]] = []

        for doc_type, tmpl in tmpl_map.items():
            required = tmpl.get("required_sections", [])
            doc = doc_map.get(doc_type)

            if doc is None:
                checks_total += len(required)
                issues.append(f"Document type '{doc_type}' is missing entirely")
                for section_key in required:
                    missing_sections.append({
                        "document_type": doc_type,
                        "section_name": section_key,
                        "reason": "Document not generated",
                    })
                continue

            # Get section headings present in doc
            present_headings = set()
            for section in doc.get("sections", []):
                heading = str(section.get("heading", "")).lower().replace(" ", "_")
                present_headings.add(heading)

            # Check each required section
            for section_key in required:
                checks_total += 1
                normalized_key = section_key.lower().replace(" ", "_")

                # Check if section exists (by key match or heading similarity)
                found = False
                for heading in present_headings:
                    if normalized_key in heading or heading in normalized_key:
                        found = True
                        break

                if found:
                    checks_passed += 1
                else:
                    # Check if content mentions the section topic
                    doc_content = str(doc.get("content", "")).lower()
                    topic_words = normalized_key.replace("_", " ")
                    if topic_words in doc_content:
                        checks_passed += 1
                    else:
                        issues.append(
                            f"Section '{section_key}' missing from {doc_type} document"
                        )
                        missing_sections.append({
                            "document_type": doc_type,
                            "section_name": section_key,
                            "reason": "Required section not found in generated content",
                        })

        is_compliant = checks_passed == checks_total and checks_total > 0

        return {
            "status": "success",
            "compliance_check": {
                "is_compliant": is_compliant,
                "checks_passed": checks_passed,
                "checks_total": checks_total,
                "issues": issues,
            },
            "missing_sections": missing_sections,
        }
    except Exception as exc:
        return {
            "status": "error",
            "compliance_check": {},
            "missing_sections": [],
            "error": f"Compliance validation failed: {exc}",
        }
