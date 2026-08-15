"""Deterministic human and machine report rendering."""

from __future__ import annotations

from typing import Any

from .canonical import canonical_json_bytes
from .policy import Diagnostic


def render_preview(payload: dict[str, Any]) -> bytes:
    lines = [f"# {payload['title']}", "", f"**Purpose:** {payload['purpose']}", "", f"**Audience:** {payload['audience']}", ""]
    for section in payload["sections"]:
        lines.extend(["#" * min(section["heading_level"] + 1, 4) + f" {section['heading']}", ""])
        for block in section["blocks"]:
            if block["type"] in ("paragraph", "callout"):
                prefix = "> " if block["type"] == "callout" else ""
                lines.extend([prefix + block["text"], ""])
            elif block["type"] == "list":
                for index, item in enumerate(block["items"], 1):
                    marker = f"{index}." if block["ordered"] else "-"
                    lines.append(f"{marker} {item}")
                lines.append("")
            elif block["type"] == "table":
                lines.append(f"**{block['caption']}**")
                lines.append("| " + " | ".join(block["headers"]) + " |")
                lines.append("| " + " | ".join("---" for _ in block["headers"]) + " |")
                lines.extend("| " + " | ".join(row) + " |" for row in block["rows"])
                lines.append("")
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def render_handoff(manifest: dict[str, Any]) -> bytes:
    artifact_lines = [
        f"- `{item['artifact_id']}`: `{item['output_filename']}` using `{item['template']['profile_id']}` `{item['template']['version']}`"
        for item in manifest["artifacts"]
    ]
    lines = [
        "# Microsoft 365 Copilot Handoff",
        "",
        f"- Package ID: `{manifest['package_id']}`",
        f"- Content digest: `{manifest['content_digest']}`",
        f"- Classification: `{manifest['classification']}`",
        f"- Locale: `{manifest['locale']}`",
        f"- Environment: `{manifest['environment']}`",
        "",
        "## Requested Word artefacts",
        "",
        *artifact_lines,
        "",
        "## Manual processing boundary",
        "",
        "1. Transfer this intact folder to the configured Microsoft 365 intake location.",
        "2. Confirm the copied `handoff-manifest.json` has the package ID and digest shown above.",
        "3. Manually invoke the separately configured Copilot Studio agent with this exact package ID.",
        "4. Do not modify this intake folder; place outputs and the processing receipt in a separate result folder.",
        "5. Do not accept returned Word files until an independent return verifier passes.",
        "",
        "This package does not upload files, invoke Copilot, or authorise replacement or publication.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def validation_report_bytes(
    package_id: str,
    content_digest: str,
    errors: list[Diagnostic],
    warnings: list[Diagnostic],
) -> tuple[bytes, bytes]:
    status = "pass" if not errors else "fail"
    payload = {
        "schema_version": "1.0",
        "package_id": package_id,
        "content_digest": content_digest,
        "status": status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
    }
    json_bytes = canonical_json_bytes(payload)
    lines = [
        "Microsoft 365 Copilot handoff validation",
        f"Status: {status.upper()}",
        f"Package ID: {package_id}",
        f"Content digest: {content_digest}",
        f"Errors: {len(errors)}",
        f"Warnings: {len(warnings)}",
    ]
    for item in [*errors, *warnings]:
        suffix = f" [{item.context}]" if item.context else ""
        lines.append(f"- {item.severity.upper()} {item.code}: {item.message}{suffix}")
    return json_bytes, ("\n".join(lines) + "\n").encode("utf-8")
