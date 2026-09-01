# Readable Chat and Summary UI

## Goal

Make factual AI Trade Desk answers and the Summary tab easy for a beginner to
read, without hiding the account details or weakening the read-only safety
boundary.

## Done looks like

- A custom question receives only the factual topic it asks about. When the
  current engine data cannot answer it, chat says so plainly instead of showing
  an unrelated P&L explanation.
- A P&L answer starts with one plain-English answer sentence, then separates
  main contributors from complete details.
- The default P&L view shows the daily result, realized and unrealized values,
  largest gain, largest loss, and any un-attributed amount. Every recorded
  trade and position remains available in a collapsed details section.
- The Summary tab is structured into “Today at a glance,” “Trading activity,”
  and “Account details” rather than rendering one unstructured text block.
- Explanatory text uses SF Pro; monetary amounts, percentages, quantities, and
  timestamps use SF Mono. Existing semantic colors and contrast remain intact.
- The disclosure and all read-only/actionable-language restrictions remain
  unchanged. No raw external news text is reintroduced.

## Design

The chat API keeps the validated topic-selector architecture. It adds an
explicit question-intent fallback: when the selector has no relevant supported
topic, the server returns a short, factual limitation instead of defaulting to
P&L. P&L remains server-rendered, but returns structured display sections:
`headline`, `key_points`, and `details`. The app renders those sections as a
brief with an expandable details disclosure; no model-generated prose reaches
the interface.

The Summary endpoint continues to return its existing factual summary text.
The macOS client parses its stable labelled sections into three visual cards,
falling back to a single “Account details” card when an older or unstructured
summary is received. This avoids changing daily engine execution.

## Constraints

- Chat continues to use only supplied account, trade, price, risk, and engine
  decision data.
- A question must never receive unrelated account data merely because a model
  selector is broad or uncertain.
- The API and Swift client support the existing legacy `answer` payload during
  rollout.
- All primary controls remain keyboard accessible with visible focus, and
  content remains readable under Dynamic Type.

## Out of scope

- New market-news display, article links, trade execution, recommendations, or
  risk-control changes.
- Charts, tabs, or a redesign of the app’s overall color system.

## Verification

- Engine tests prove unsupported custom questions return the plain fallback and
  P&L responses contain a concise headline, key points, and full details.
- Swift tests prove section parsing and legacy-answer decoding.
- The full engine suite and macOS app build pass.
