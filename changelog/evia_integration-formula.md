# EVIA: integration formula

## Problem

`(1 / k * k)` equals `1`, so Integration compares the raw `sc_score`
against `0.7`. Extraction initializes this score to `1`, causing every
candidate to pass, including concepts with no validation votes.

The paper (Eq. 1, p. 15469) describes score aggregation and thresholding but
does not specify normalization fully. This fork interprets confidence as
the equally weighted frequency of acceptance across validation rounds.

## Actual vs proposed

| Item | Actual (upstream `81f2ce2`) | Proposed (implemented in this fork) |
| --- | --- | --- |
| Integration score | `(1 / k * k) * sc_score` | `(sc_score - 1) / (model_count * k)` |
| Extraction baseline | Initial `1` counts toward acceptance | Subtract `1`; count only validation votes |
| Model count | Not passed to Integration | Use `len(models)` from the pipeline |
| Acceptance | Raw score `>= 0.7`, or one model accepts all `k` rounds | Normalized score `>= alpha`; default `alpha = 0.7`, with no alternative bypass |
| Per-model counter | Starts at `1`; `sc_max[index] + 1` has no effect | Starts at `0`; increment with `+= 1`; retained for diagnostics |
| Invalid inputs | No vote-range or denominator checks | Reject nonpositive counts, invalid thresholds, mismatched scores, and out-of-range votes |

With three models and five rounds: `10/15 = 0.667` is rejected;
`11/15 = 0.733` is accepted. A concept accepted by only one model in all
five rounds scores `5/15 = 0.333` and is rejected.

Replaying only two author paragraphs (06:35–08:07) retains aerobic respiration,
enzymes, and energy supply. The published Integration file retains only energy
supply; its generating configuration is unknown, so this is not an exact reproduction.
