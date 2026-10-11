# EVIA: optional external resources

## Problem

Augmentation is commented out. Enabling it requires editing code and provides
no independent control over ConceptNet expansion and Wikipedia retrieval.

## Actual vs proposed

| Item | Actual (upstream `81f2ce2`) | Proposed (implemented in this fork) |
| --- | --- | --- |
| Resource control | Commented-out call | `--use-conceptnet` and `--use-wikipedia`, independently enabled |
| Default | Augmentation skipped | Both resources off; run Extraction, Verification, Integration only |
| Resource loading | Import both modules at startup | Load each module only when its resource is enabled |
| Wikipedia result | Compare a dictionary with `"not found"` | Read the concept's summary; handle missing/error values |
| Reusing EVI output | Skip processed input without restoring concepts | Restore concepts from completed Integration files before optional augmentation |
| Output | Commented-out writer | Per-directory `_Augmentation.json`, recording resource flags and concept/explanation pairs |

```bash
python ExtractMultimodalConcepts/NER.py lessons/ --subject Biology
python ExtractMultimodalConcepts/NER.py lessons/ --subject Biology --use-conceptnet
python ExtractMultimodalConcepts/NER.py lessons/ --subject Biology --use-wikipedia
python ExtractMultimodalConcepts/NER.py lessons/ --subject Biology --use-conceptnet --use-wikipedia
```

Set `SCIMKG_LLM_URL` (full chat-completions URL) and `SCIMKG_LLM_API_KEY`
for the existing LLM calls. With ConceptNet alone, explanations use the LLM
without Wikipedia grounding.

Remaining fixes: ConceptNet extraction rules are still empty. Wikipedia still
uses the author's local proxy and Baidu translation configuration. These flags
control access; live augmentation is not yet validated.
