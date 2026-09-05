# Readable Chat and Summary UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans task-by-task.

**Goal:** Deliver readable, question-specific AI replies and a structured beginner-friendly Summary tab.

**Architecture:** The API adds structured factual P&L fields and a deterministic unsupported-question fallback while preserving legacy answer decoding. SwiftUI renders a short brief plus expandable details and parses the existing labelled summary into semantic cards.

**Tech Stack:** Python/FastAPI/pytest and SwiftUI/XCTest.

### Task 1: Chat intent and structured P&L contract

**Files:** engine/src/autotrader/ipc.py; engine/src/autotrader/pnl_explanation.py; engine/tests/test_ipc.py

- [ ] Write failing tests: unsupported selector returns a plain factual limitation; P&L response includes headline, key_points, details while legacy answer remains.
- [ ] Run:
~~~bash
PYTHONPATH=engine/src engine/.venv/bin/python -m pytest engine/tests/test_ipc.py -q
~~~
Expected: FAIL because the structured keys and fallback do not exist.
- [ ] Implement a validated response shape:
~~~python
{"answer": headline, "headline": headline, "key_points": points, "details": details, "disclaimer": _INFORMATIONAL_DISCLAIMER}
~~~
Return the existing safe limitation when no supported topic can answer. P&L renderer returns one beginner-friendly headline, key points for total/realized/unrealized/largest contributors/reconciliation, and complete factual details.
- [ ] Re-run focused tests and commit:
~~~bash
git add engine/src/autotrader/ipc.py engine/src/autotrader/pnl_explanation.py engine/tests/test_ipc.py
git commit -m "feat: structure readable chat responses"
~~~

### Task 2: Decode and render the readable brief

**Files:** app/TradingAgentApp/Models.swift; app/TradingAgentApp/AITradeDeskView.swift; app/TradingAgentApp/Tests/TradingAgentAppTests.swift

- [ ] Write failing XCTest cases for structured ChatResponse decoding and legacy answer fallback.
- [ ] Run:
~~~bash
cd app/TradingAgentApp && swift test
~~~
Expected: FAIL because headline/key_points/details are absent.
- [ ] Add optional headline/key_points/details to ChatResponse. Render SF Pro headline/body, SF Mono numeric key points, and a DisclosureGroup labelled “All details” for complete records. Preserve disclosure, text selection, accessibility labels, keyboard focus, and legacy messages.
- [ ] Re-run tests and commit:
~~~bash
git add app/TradingAgentApp/Models.swift app/TradingAgentApp/AITradeDeskView.swift app/TradingAgentApp/Tests/TradingAgentAppTests.swift
git commit -m "feat: present chat as readable brief"
~~~

### Task 3: Structure the Summary tab

**Files:** app/TradingAgentApp/SummaryView.swift; app/TradingAgentApp/Tests/TradingAgentAppTests.swift

- [ ] Write failing tests for a pure SummarySections parser: labelled text maps to Today at a glance, Trading activity, Account details; unlabelled legacy text maps entirely to Account details.
- [ ] Run:
~~~bash
cd app/TradingAgentApp && swift test
~~~
Expected: FAIL because SummarySections does not exist.
- [ ] Add a pure parser and render three SF Pro cards with section headings, monospaced numeric fragments, Dynamic Type-safe multiline text, and a legacy fallback card.
- [ ] Re-run tests and commit:
~~~bash
git add app/TradingAgentApp/SummaryView.swift app/TradingAgentApp/Tests/TradingAgentAppTests.swift
git commit -m "feat: structure daily summary UI"
~~~

### Task 4: Verify and review

- [ ] Run:
~~~bash
PYTHONPATH=engine/src engine/.venv/bin/python -m pytest engine/tests -q
bash app/build-app.sh
git diff origin/main...HEAD --check
~~~
Expected: complete engine suite and app build pass; no whitespace errors.
- [ ] Review the final diff against docs/specs/readable-chat-and-summary-ui.md, then request independent spec and code-quality reviews before PR creation.
