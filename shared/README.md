# `shared/` — reusable library code

Code that more than one session, lab, or the FIA project depends on lives here, so we
never copy-paste the same boilerplate across weeks.

- **`shared/llm/`** — a small multi-provider LLM client wrapping OpenRouter, OpenAI,
  and Anthropic behind one interface. Introduced in **Session 01** and reused
  everywhere after.

Import it as a package from the repo root:

```python
from shared.llm import chat

print(chat("Explain the ReAct loop in one sentence."))
```

As the cohort progresses we add more shared modules here (e.g. retrieval helpers,
tracing setup). Each is introduced in the session that first needs it.
