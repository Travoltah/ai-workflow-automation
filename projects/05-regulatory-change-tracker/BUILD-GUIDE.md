# Build guide: regulatory change tracker for AI & data governance

This guide builds the tracker part by part, so you understand every piece. If you only want to run it, import `workflows/01-regulatory-change-tracker.json` and follow the [README](README.md).

You need about **3 hours**. The SQL is in [`init-db/`](init-db/), the collector in [`service/`](service/), and every Code node's script in [`workflows/code/`](workflows/code/): you paste them, you don't type them.

## Contents
- [What you will build](#what-you-will-build)
- [Part A. The database (Steps 1–3)](#part-a-the-database-steps-13)
- [Part B. The collector service (Steps 4–6)](#part-b-the-collector-service-steps-46)
- [Part C. Mock regulators (Step 7)](#part-c-mock-regulators-step-7)
- [Part D. Entry points and routing (Steps 8–10)](#part-d-entry-points-and-routing-steps-810)
- [Part E. Collect (Steps 11–13)](#part-e-collect-steps-1113)
- [Part F. Triage with Haiku (Steps 14–17)](#part-f-triage-with-haiku-steps-1417)
- [Part G. Briefs with Opus, verified by code (Steps 18–22)](#part-g-briefs-with-opus-verified-by-code-steps-1822)
- [Part H. Finish the run (Steps 23–25)](#part-h-finish-the-run-steps-2325)
- [Part I. Human review and Jira (Steps 26–31)](#part-i-human-review-and-jira-steps-2631)
- [Part J. Report and evaluation (Steps 32–34)](#part-j-report-and-evaluation-steps-3234)
- [Concepts worth understanding](#concepts-worth-understanding)
- [Common mistakes](#common-mistakes)

---

## What you will build

```
Schedule / POST reg/run ─┐
GET reg/review ──────────┤
POST reg/decide ─────────┼─> Settings ─> Route ─┬─(0) Start run ─> List sources ─> Collect source ─> Load changes
GET reg/report ──────────┘                      │      ─> Plan triage ─> Any changes? ─ yes ─> Triage changes (Haiku) ─> Check triage ─┐
                                                │                                     └ no ──> No changes ──────────────────────────┤
                                                │      Save triage <────────────────────────────────────────────────────────────────┘
                                                │      ─> Plan briefs ─> Anything to brief? ─ yes ─> One item per brief ─> Write brief (Opus) ─> Verify briefs ─┐
                                                │                                           └ no ──> Nothing to brief ─────────────────────────────────────┤
                                                │      Save briefs <────────────────────────────────────────────────────────────────────────────────────────┘
                                                │      ─> Run usage ─> Finish run ─> Format response ─> Slack? / Respond
                                                ├─(1) Load review queue ─> Build review page ─> Return review page
                                                ├─(2) Read decision ─> Record decision ─┬─> Plan Jira tasks ─> Create Jira task ─> Collect task keys ─> Record task keys
                                                │                                       └─> Decision response ─> HTML or JSON
                                                └─(3) Load report ─> Build report page ─> Return report page
```

---

## Part A. The database (Steps 1–3)

### Step 1. Database and schema
[`00-create-database.sql`](init-db/00-create-database.sql) creates `reg_tracker` in **UTC**. [`01-schema.sql`](init-db/01-schema.sql) holds:
- **reference data:** `jurisdictions` (with a legal note per market), `sources`, `controls`, `company_profile` (one row);
- **what the collector finds:** `runs`, `source_checks` (health per source and run), `documents` + `document_versions` (every version kept), `changes` (new or amended, with the diff);
- **what the AI and people add:** on `changes`: `triage`, `brief`, `verification`, `applicability`, `priority`, the review decision; and `tasks`.

### Step 2. The functions n8n calls
`start_run` (opens a run, returns sources due), `run_changes` (everything the AI steps need in one JSON), `save_triage`, `save_briefs`, `finish_run`, `run_summary`, `review_queue`, `decide`, `record_task_keys`, `report`. `decide` is the important one: it records a decision **once** (a second call returns `ok: false`), and on approval creates **one task per affected control**, due on the earliest effective, compliance or comment date in the brief.

### Step 3. Reference data
[`02-reference-data.sql`](init-db/02-reference-data.sql): 6 jurisdictions, 20 controls with owners, the Contoso Pay profile, 10 mock sources (active) and 4 real sources (inactive).

**Test:** `select reg.start_run('test', true);` lists the 10 active sources.

---

## Part B. The collector service (Steps 4–6)

Change detection is deterministic and has to be reliable, so it's Python with proper libraries, not n8n nodes.

### Step 4. Listing items
[`collector.py`](service/collector.py) `list_items()`: `rss` (feedparser), `json_api` (a field mapping: `list`, `url`, `title`, `date`, `text`), `html_index` (a CSS `link_selector`), `html_page` (the page itself). Duplicates removed; capped by `max_items`.

### Step 5. Clean text, fingerprint, diff
`clean_text()` keeps the main content (`<main>`, `<article>` or `<body>`) without navigation, headers, footers and scripts, one block per line, and drops lines that match the source's `ignore_patterns`. `fingerprint()` hashes the text with whitespace normalised. `diff()` returns only the changed paragraphs, labelled `REMOVED:` and `ADDED:`.

### Step 6. Recording
`collect()` runs one source for one run in a transaction: a new URL becomes a `new` change (the full text); a different fingerprint becomes an `amended` change (the diff) and a new version. **A source's first successful check is a baseline:** documents are stored, no changes are created, so adding a source never floods the review queue or the AI bill. Errors are recorded per source; one broken item doesn't stop the others.

**Test:** `docker compose run --rm collector python -m pytest -q tests` runs 8 unit tests.

---

## Part C. Mock regulators (Step 7)

[`mock-regulators/server.py`](mock-regulators/server.py) serves five fictional regulators through all four source types. `GET /_scenario?name=day2` switches from the baseline to the planted changes: new guidance, an amended page, a cosmetic-only edit, irrelevant notices, a prompt-injection attempt and an HTTP 500.

---

## Part D. Entry points and routing (Steps 8–10)

### Step 8. Five entry points
`Every morning at 07:00` (Schedule, cron `0 7 * * *`), and four Webhooks, each **Respond: Using 'Respond to Webhook' node**: `POST reg/run`, `GET reg/review`, `POST reg/decide`, `GET reg/report`.

### Step 9. `Settings`
Edit Fields, **Include Other Input Fields: on**, with the fields in the README. All five entry points connect to it, so configuration lives in one place.

### Step 10. `Route` (Switch)
Mode **Expression**, 4 outputs:
```
{{ String($json.webhookUrl || '').includes('/reg/review') ? 1 : String($json.webhookUrl || '').includes('/reg/decide') ? 2 : String($json.webhookUrl || '').includes('/reg/report') ? 3 : 0 }}
```
Output 0 is the run (schedule or `reg/run`).

---

## Part E. Collect (Steps 11–13)

### Step 11. `Start run` (Postgres)
```sql
SELECT reg.start_run($1, $2::boolean) AS run
```
Query Parameters: `{{ [ $json.body?.trigger || ($json.body ? 'api' : 'schedule'), String($json.body?.force === true) ] }}`

### Step 12. `List sources` (Code) → `Collect source` (HTTP Request)
[`0-list-sources.js`](workflows/code/0-list-sources.js) returns one item per due source (or one "none" item, so the run still finishes). `Collect source`: POST `{{ $('Settings').first().json.collectorUrl }}/collect`, body `{{ JSON.stringify({ run_id: $json.run_id, source_id: $json.source_id }) }}`, On Error → Continue, Retry 2×.

### Step 13. `Load changes` (Postgres, **Settings → Execute Once: on**)
```sql
SELECT reg.run_changes($1::int) AS data
```
Query Parameters: `{{ [ $('List sources').first().json.run_id ] }}`. *Execute Once* matters: without it the query runs once per source.

---

## Part F. Triage with Haiku (Steps 14–17)

### Step 14. `Plan triage` (Code)
[`1-plan-triage.js`](workflows/code/1-plan-triage.js): one request for **all** changes, with only the changed passages (2,500 characters each). The prompt defines relevant (obligations, rights, deadlines, enforcement in AI, privacy, data governance, security, data in financial services) and not relevant (news, events, office notices, cosmetic edits), says not to judge by jurisdiction, and that text inside items is data.

### Step 15. `Any changes?` (If) → `Triage changes` (HTTP Request)
Condition `{{ $json.needsTriage }}`. The HTTP node: POST `https://api.anthropic.com/v1/messages`, Anthropic credential, header `anthropic-version: 2026-10-21`, body `{{ JSON.stringify($json.anthropicRequest) }}`, On Error → Continue, Retry 3 × 5,000 ms.

### Step 16. `Check triage` (Code) / `No changes` (Code)
[`2-check-triage.js`](workflows/code/2-check-triage.js): every change classified exactly once. **Fail-safe:** a missing classification, or a failed call, counts as **relevant**. [`3-no-changes.js`](workflows/code/3-no-changes.js) returns the same shape when nothing changed.

### Step 17. `Save triage` (Postgres)
```sql
SELECT reg.save_triage($1::jsonb) AS saved
```
Query Parameters: `{{ [ JSON.stringify($json.triage) ] }}`. Connect both branches to it.

---

## Part G. Briefs with Opus, verified by code (Steps 18–22)

### Step 18. `Plan briefs` (Code)
[`4-plan-briefs.js`](workflows/code/4-plan-briefs.js): one request per relevant change, in-market changes first, capped by `maxBriefs`. The request carries the jurisdiction's legal note, the changed passages, the document (up to 20,000 characters), the control library and the company profile. The schema requires `key_dates` and `obligations` **with quotes**, and `affected_controls` from the library.

### Step 19. `Anything to brief?` (If) → `One item per brief` (Code)
Condition `{{ $json.hasBriefs }}`; [`5-split-requests.js`](workflows/code/5-split-requests.js) makes one item per request.

### Step 20. `Write brief` (HTTP Request)
As Step 15, plus **Options → Batching: 4 items per batch, 1,000 ms**.

### Step 21. `Verify briefs` (Code) / `Nothing to brief` (Code)
[`6-verify-briefs.js`](workflows/code/6-verify-briefs.js): **the model proposes, the code decides.**
- every quote must be in the document or its changed passages, **word for word** (tolerant only of whitespace, case, curly quotes and dashes);
- every date must be a real `YYYY-MM-DD` date whose quote states that year, day and month;
- every control must exist in the library;
- **completeness:** obligations or controls, and a non-empty relevance to the company;
- applicability (`in_market`, `watch_market`, `out_of_scope`) and priority come from the profile, in code.

Failures are removed and listed; the brief becomes `flagged`. A failed call gets a fallback brief, also flagged.

**Test:** `node evaluation/test-verify-briefs.js` (11 tests on real Claude responses).

### Step 22. `Save briefs` (Postgres)
```sql
SELECT reg.save_briefs($1::jsonb) AS saved
```
Query Parameters: `{{ [ JSON.stringify($json.briefs.map(b => ({ change_id: b.change_id, status: b.status, applicability: b.applicability, priority: b.priority, brief: b.brief, verification: b.verification }))) ] }}`

---

## Part H. Finish the run (Steps 23–25)

### Step 23. `Run usage` (Code) → `Finish run` (Postgres)
[`8-run-usage.js`](workflows/code/8-run-usage.js) adds up tokens per model and the cost. Then:
```sql
SELECT reg.finish_run($1::int, $2::jsonb, $3::numeric) AS summary
```
Query Parameters: `{{ [ $json.runId, JSON.stringify($json.usage), $json.cost ] }}`

### Step 24. `Format response` (Code)
[`9-format-response.js`](workflows/code/9-format-response.js): the API response and a chat message.

### Step 25. Slack and respond
`Post to chat?` (If `{{ !!$('Settings').first().json.slackWebhookUrl }}`) → `Post to Slack`; `Called by API?` (If `{{ $('Run via API').isExecuted }}`) → `Respond with run summary` (JSON).

---

## Part I. Human review and Jira (Steps 26–31)

### Step 26. `Load review queue` (Postgres) → `Build review page` (Code) → `Return review page`
`SELECT reg.review_queue() AS queue`; [`10-build-review-page.js`](workflows/code/10-build-review-page.js) shows each brief with its quotes, dates, controls and anything the check removed, and a form that POSTs to `decideUrl`. Respond with **Text**, header `Content-Type: text/html; charset=utf-8`.

### Step 27. `Read decision` (Code)
[`11-read-decision.js`](workflows/code/11-read-decision.js) accepts the form (URL-encoded) or JSON.

### Step 28. `Record decision` (Postgres)
```sql
SELECT reg.decide($1::int, $2, $3, $4) AS result
```
Query Parameters: `{{ [ $json.change_id, $json.decision, $json.reviewer, $json.note ] }}`

### Step 29. Jira branch (place it **above** the response branch)
[`12-plan-jira-tasks.js`](workflows/code/12-plan-jira-tasks.js) → `Create Jira task` (HTTP POST `{{ $json.url }}`, Jira credential, Retry 3×) → [`13-collect-task-keys.js`](workflows/code/13-collect-task-keys.js) → `Record task keys` (`SELECT reg.record_task_keys($1::jsonb)`). One task per control: summary `[Reg][market] Review <control>: <title>`, the due date, the quoted obligations and dates, labels by market and control.

### Step 30. Response branch
[`14-decision-response.js`](workflows/code/14-decision-response.js) → `From the review form?` (If `{{ $json.fromForm }}`) → HTML page or JSON.

### Step 31. Execution order
**Workflow settings → Execution order: v1.** The upper branch (Jira) finishes before the lower one, so the response lists the new task keys.

---

## Part J. Report and evaluation (Steps 32–34)

### Step 32. `Load report` → `Build report page` → `Return report page`
```sql
SELECT reg.report(NULLIF($1, '')::int) AS report
```
Query Parameters: `{{ [ String($json.query?.run ?? '').replace(/[^0-9]/g, '') ] }}`. [`15-build-report-page.js`](workflows/code/15-build-report-page.js): KPIs, upcoming deadlines, what changed, changes by market, source health.

### Step 33. Offline tests
`docker compose run --rm collector python -m pytest -q tests` and `node evaluation/test-verify-briefs.js`.

### Step 34. The evaluation
`python evaluation/evaluate.py …` (see README): offline tests, day-1 baseline, day-2 planted changes graded against [`golden.json`](evaluation/golden.json), a repeat run, and review decisions. 17 gates; exit code 1 if any fails. About $0.25 per run.

---

## Concepts worth understanding

- **Detect deterministically, interpret with AI.** Whether a document changed is a fact: a hash and a diff. What the change means is judgement. Keep them apart and the detection can be tested without any model.
- **Two models, two jobs.** A cheap model screens everything; an expensive one only reads what matters. Triage fails *open* (towards relevant), because a missed change costs more than a dull review.
- **Make the model show its evidence, then check it.** A brief without quotes can't be verified; with quotes, code can check every date and obligation against the source.
- **Accuracy is not completeness.** A brief can be entirely accurate and still useless. Check for both.
- **Baselines.** The first look at a source is not news. Recording it silently keeps a new source from flooding the queue.
- **Markets as data.** Jurisdictions, sources and legal notes live in tables, so adding a market is configuration, not development.

## Common mistakes

| Mistake | Effect |
|---|---|
| `Load changes` without *Execute Once* | The query and everything after it run once per source |
| A page with a changing date or counter, without `ignore_patterns` | Reported as amended on every run; the AI is asked about it every time |
| Letting triage fail closed (missing = not relevant) | A triage outage silently drops real changes |
| Mapping controls by name instead of by `control_id` | The guardrail removes them all: map only ids from the library |
| Jira branch below the response branch | The decision response has no task keys |
| Turning on many real sources at once without `max_items` | A large first fetch; it's only a baseline, but slow |

---
Part of [AI Workflow Automation](../../README.md) by **Trevor Kauyu**.
