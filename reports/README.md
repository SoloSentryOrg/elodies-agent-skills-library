# Assessment reports

This directory contains the repository's primary deliverables: evidence-led
security assessments of MCP extensions and integrations for VS Code and Visual
Studio, plus their retained, non-sensitive supporting metadata. It is an
artifact root, not an Agent Skill.

Assess the complete installation surface. When an extension or MCP integration
packages, installs, or requires Agent Skills, include those skills in the same
security review and distinguish them from MCP tools, prompts and resources.

Do not publish raw third-party packages, source archives, scanner caches,
credentials, customer data, private operational evidence, or disposable-runtime
captures here. Authoritative reports must pass the repository security gate and
the assessment skill's fail-closed document quality checks before publication.

## Library layout

Store every assessment as a self-contained directory directly under
`reports/`. The directory must contain its authoritative `.docx` report.
Retained evidence, stage outputs and a reproducible report builder should remain
in that same directory when available.

```text
reports/
└── <product-version>-assessment/
    ├── <authoritative-assessment>.docx
    ├── evidence/
    ├── stages/
    └── build_report.py
```

Do not place assessment DOCX files directly in `reports/`. Earlier assessments
imported into this central library must each receive their own containing
directory, even when only the authoritative report is available.
