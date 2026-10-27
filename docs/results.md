# Results log

Every number in this file comes from a command that was actually run. Each
section lists the command, the environment and the raw output.

## 1. NLI faithfulness scorer: before and after the fix

**Date:** 2026-10-27. **Machine:** cloud dev container, 4 vCPU, CPU only.
**Model:** `facebook/bart-large-mnli`, transformers 5.21.0, torch 2.14.1+cpu.

Same context for all three cases:
`"The client's portfolio holds 60% stocks and 40% bonds. The annual fee is 0.5%."`

Command (from `backend/`, with the minimum env vars set):

```bash
PYTHONPATH=. SECRET_KEY=x DATABASE_URL=postgresql+asyncpg://u:p@localhost/db \
  REDIS_URL=redis://localhost OPENAI_API_KEY=sk-test python nli_check.py
```

Before (commit `e18c0a3`, original scorer):

```
raw pipeline output labels: ['The portfolio holds 60% stocks and 40% bonds.'] scores: [0.9851950407028198]
supported 0.0
contradicted 0.0
unrelated 0.0
```

The zero-shot pipeline returns the candidate sentence as its label, so
`scores.get('ENTAILMENT', 0.0)` always fell through to 0.0.

After (this branch, `FaithfulnessScorer` using plain NLI):

```
supported: 0.9936
contradicted: 0.0002
unrelated: 0.0572
```

Related bug, also fixed: because every answer scored 0.0, the QA graph's
retry check always fired, and `retry_count` was never written to state, so
the graph looped until LangGraph raised `GraphRecursionError`.
`backend/tests/test_qa_agent_retry.py` reproduces that failure on the old
code and passes on the fix.
