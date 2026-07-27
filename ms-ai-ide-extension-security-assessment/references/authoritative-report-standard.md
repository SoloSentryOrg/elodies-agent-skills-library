# Authoritative report acceptance standard

Use this standard to prevent a detailed assessment from being reduced to a polished executive brief. These are minimum structural floors, not content targets. Passing them never substitutes for accurate analysis, primary evidence, secure runtime handling, or professional judgment.

## Mandatory acceptance profile

- Include document control, revision history, contents, the complete shared overview, self-contained VS Code and Visual Studio parts, Agent Skills disposition, consolidated sections, evidence register, references, appendices, and glossary.
- Include at least five executive outcomes and explicit approval conditions.
- Include a numbered architecture, data-flow, or trust-boundary figure with accessible alternative text.
- Include complete installation-manifest, framework-disposition, controls-roadmap, monitoring, risk-register, evidence-register, and references tables.
- Include complete individual finding records; do not rely only on a consolidated risk table.
- Use stable `REF-nnn`, `EVD-nnn`, and finding identifiers throughout.
- Internally hyperlink in-text references to unique Word bookmarks and externally hyperlink each reference-table source.
- State analysis selections and results for static analysis, malware review, runtime analysis, and privacy review.
- State `Verified`, `Inferred`, `Not observed`, `Not applicable`, and `Unknown` evidence dispositions where each is relevant.
- Record Microsoft Word rendering and page inspection, accessibility, metadata/privacy, citation-link, scoring, and secure-review results.

## Anti-truncation floors

Unless a stricter repository validator applies, an authoritative combined-IDE report must contain at least:

- 4,000 words across document paragraphs and tables;
- 40 structured headings;
- 15 substantive tables;
- one figure or diagram;
- 12 unique reference bookmarks;
- 12 internally hyperlinked in-text references; and
- 12 external reference hyperlinks.

If the evidence genuinely cannot support these floors, do not pad the report. Deliver a clearly labelled `Draft` or `Defer pending evidence` assessment and identify the evidence needed for an authoritative version.

## Prohibited substitutions

- A five-page executive summary is not an authoritative assessment.
- Clean rendering or a zero-finding accessibility audit is not evidence of methodological completeness.
- Stage-output files are not automatically validated findings.
- A consolidated risk table is not a substitute for per-finding analysis.
- A host-verification plan is not a substitute for selected runtime analysis when a safe runtime environment is available.
- Model, desktop, or IDE choice is not an acceptable reason to omit required sections or QA.
