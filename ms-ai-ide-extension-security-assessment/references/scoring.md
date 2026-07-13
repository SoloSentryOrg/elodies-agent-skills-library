# Risk and confidence scoring

## Likelihood and impact

Score each from 1 to 5.

| Score | Likelihood | Impact |
|---:|---|---|
| 1 | Rare | Negligible |
| 2 | Unlikely | Minor |
| 3 | Possible | Moderate |
| 4 | Likely | Major |
| 5 | Almost certain | Severe |

`Inherent score = likelihood × impact` before proposed/verified controls.

| Score | Rating |
|---:|---|
| 1–4 | Low |
| 5–9 | Moderate |
| 10–16 | High |
| 17–25 | Critical |

## Control strength

| Score | Strength | Meaning |
|---:|---|---|
| 0 | None/unknown | No reliable evidence of an effective control |
| 1 | Weak | Partial, informal, bypassable, or untested |
| 2 | Moderate | Designed and partly evidenced; gaps remain |
| 3 | Strong | Preventive/detective coverage is evidenced and tested |

Do not subtract control strength mechanically. Re-score residual likelihood and impact after considering verified controls, then calculate `residual score = residual likelihood × residual impact`. Explain why controls change either dimension.

## Required finding record

- ID, title, affected IDE/version/component
- threat scenario, asset, attacker/precondition, evidence IDs
- likelihood, impact, inherent score/rating
- existing controls and control-strength rationale
- residual likelihood, impact, score/rating
- recommended remediation, priority, owner, target date, verification test
- framework mappings and confidence

## Confidence

- **High:** direct observation and corroborating primary evidence; version-specific.
- **Medium:** credible primary evidence with limited direct verification or minor inference.
- **Low:** incomplete, conflicting, indirect, or stale evidence.

Confidence is not risk severity. Never lower severity solely because confidence is low; identify the evidence needed to resolve uncertainty.
