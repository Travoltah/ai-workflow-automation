# Build guide: AI data quality monitor

This guide builds the monitor by hand, part by part, so you understand every piece. If you only want to run it, import `workflows/01-data-quality-monitor.json` and follow the [README](README.md) instead.

You need about **2 hours**. The SQL is in [`init-db/`](init-db/) and every Code node's script is in [`workflows/code/`](workflows/code/): you paste them, you don't type them. This guide explains what each one does and how to test it.

## Contents
- [What you will build](#what-you-will-build)
- [Before you start](#before-you-start)
- [Part A. The database (Steps 1–4)](#part-a-the-database-steps-14)
- [Part B. Sample data and planted defects (Steps 5–6)](#part-b-sample-data-and-planted-defects-steps-56)
- [Part C. Triggers and checks (Steps 7–10)](#part-c-triggers-and-checks-steps-710)
- [Part D. AI explanations, checked by code (Steps 11–15)](#part-d-ai-explanations-checked-by-code-steps-1115)
- [Part E. Jira (Steps 16–19)](#part-e-jira-steps-1619)
- [Part F. Finish, notify, respond (Steps 20–24)](#part-f-finish-notify-respond-steps-2024)
- [Part G. The report page (Steps 25–28)](#part-g-the-report-page-steps-2528)
- [Part H. Evaluate (Steps 29–31)](#part-h-evaluate-steps-2931)
- [Concepts worth understanding](#concepts-worth-understanding)
- [Common mistakes](#common-mistakes)

---

## What you will build

```
Schedule 06:00 ─┐
POST /dq/run ───┴─> Settings ─> Run checks (SQL) ─> Plan explanations ─> Any new failures?
                                                                          ├─ yes ─> Explain failures (Claude) ─> Check explanations ─┐
                                                                          └─ no  ─> No new failures ──────────────────────────────────┤
                                                                                                                                      v
                                                                                                                         Save explanations
                                                       ┌──────────────────────────────────────────────────────────────────────────┤
                                                       v  (runs first)                                                             v
                                   Plan Jira updates ─> Update Jira ─> Collect Jira keys ─> Remember Jira keys          Finish run ─> Format response
                                                                                                                                         ├─> Post to chat? ─> Post to Slack
                                                                                                                                         └─> Called by API? ─> Respond with summary
GET /dq/report ─> Load report ─> Build report page ─> Return report page
```

## Before you start

- The stack from the README running (`docker compose --profile demo up -d`), with n8n at http://localhost:5678
- The three credentials from README step 4 (Postgres to `contoso_dq`, Anthropic, Jira)
- Python 3.9+ for the data generator; Node.js for the guardrail tests (optional)
- In n8n: **Workflow settings → Execution order: v1**. Part E depends on it.

---

## Part A. The database (Steps 1–4)

The database does the deterministic work: it runs the rules, keeps the history, and manages incidents. n8n only orchestrates, so the core can be tested with plain SQL.

### Step 1. Create the database
[`init-db/00-create-database.sql`](init-db/00-create-database.sql) creates `contoso_dq` and sets its time zone to **UTC**. Day boundaries (the daily ledger, daily volume) must be the same for every client, or the ledger checks fail on every row.

### Step 2. The schema
[`init-db/01-schema.sql`](init-db/01-schema.sql) has three parts:
- **`wallet.*`**: the monitored data. There are **no foreign keys on purpose**: data from several source systems lands without them in most warehouses, and integrity is the monitor's job.
- **`dq.*` tables**: `rules`, `runs`, `results` (count, 5 sample rows, up to 1,000 failing ids per rule and run), `incidents`. A partial unique index allows **one open incident per rule**.
- **Functions** n8n calls: `run_checks`, `save_explanations`, `record_jira`, `finish_run`, `run_summary`, `report`, plus three views for dashboards.

### Step 3. The rules
[`init-db/02-rules.sql`](init-db/02-rules.sql) inserts 16 rules. The contract: **a query that returns one row per violation, with two columns: the record id, then a detail text.** `run_checks` renames the columns by position (`AS t(record_id, detail)`), so rule authors don't need aliases.

Keep personal data **out of the detail**: it is sent to Claude. Use ids and values that explain the fault (`'kyc_status "approved"'`), not names.

### Step 4. How `dq.run_checks()` works
For each active rule it runs `EXECUTE format(...)` around the rule's SQL to get the count, 5 sample rows and up to 1,000 ids, catching any SQL error as status `error`. Then three statements manage incidents:
1. **new**: a failing rule with no open incident opens one;
2. **ongoing**: a failing rule with an open incident updates `last_seen_run` and `last_count`;
3. **resolved**: a passing rule closes its open incident. (An **errored** rule leaves its incident open: no data is not good data.)

It returns one JSON with the counts and an `actions` list, each enriched with the rule, the evidence and the Jira key, so n8n needs no further queries.

**Test:** `psql -d contoso_dq -c "select dq.run_checks('test')"`. On an empty database every rule passes.

---

## Part B. Sample data and planted defects (Steps 5–6)

### Step 5. Generate the data
```bash
python scripts/generate_data.py            # 16 planted defects, one per rule
python scripts/generate_data.py --clean    # passes every rule
docker exec -i dq-postgres psql -U <user> -d contoso_dq -q < data/seed.sql
```
Clean data obeys every rule **by construction**: transactions are generated in time order and a debit larger than the balance is marked *failed*; fees use the same half-up rounding as Postgres; the ledger is built from the completed transactions. Defects are planted afterwards, and each one is recorded in `evaluation/planted-defects.json` with **the exact record ids** its rule must report.

### Step 6. Check the rules against the answer key
```sql
select dq.run_checks('manual');
select rule_code, status, failing_count, record_ids from dq.results where run_id = (select max(run_id) from dq.runs);
```
**Test:** all 16 rules fail, and each `record_ids` equals the `expected_record_ids` for that rule in `planted-defects.json`. Then load `--clean` data with `--keep-history`, run again: 0 failures and 16 incidents resolved.

---

## Part C. Triggers and checks (Steps 7–10)

### Step 7. `Every morning at 06:00` (Schedule Trigger)
Rule: **Cron**, `0 6 * * *`. It runs in n8n's time zone (`GENERIC_TIMEZONE`).

### Step 8. `Run via API` (Webhook)
**POST**, path `dq/run`, **Respond: Using 'Respond to Webhook' node**. A body like `{"trigger": "manual"}` labels the run.

### Step 9. `Settings` (Edit Fields)
Mode **Manual**, **Include Other Input Fields: on** (so the webhook body passes through). Fields: `model`, `sampleRows`, `jiraEnabled`, `jiraBaseUrl`, `jiraProjectKey`, `jiraIssueType`, `slackWebhookUrl`, `reportUrl`. See the README for values. Connect both triggers to it.

### Step 10. `Run checks` (Postgres)
Operation **Execute Query**:
```sql
SELECT dq.run_checks($1, $2::int) AS result
```
Options → **Query Parameters**: `{{ [ $json.body?.trigger || ($json.body ? 'api' : 'schedule'), $json.sampleRows ] }}`

Parameters are passed separately from the SQL, so nothing is pasted into the query by hand.

**Test:** execute the workflow from the API trigger. `Run checks` returns one item with `result.actions` (16 `new` actions on defect data).

---

## Part D. AI explanations, checked by code (Steps 11–15)

### Step 11. `Plan explanations` (Code)
Mode **Run Once for All Items** · paste [`code/1-plan-explanations.js`](workflows/code/1-plan-explanations.js).

It keeps only the **new** incidents (ongoing and resolved ones need no AI), **masks emails** while keeping their shape (`t*****.m***@example`), and builds one Anthropic request: a system prompt that states the facts are facts and asks for cause, impact, fix, severity, confidence, evidence and related rules; and a JSON schema for **structured outputs**. It also records every id Claude is shown (`sentSamples`), for the check in Step 14.

### Step 12. `Any new failures?` (If)
Condition: `{{ $json.needsExplanation }}` **is true**.

### Step 13. `Explain failures` (HTTP Request)
- **POST** `https://api.anthropic.com/v1/messages`, Authentication **Predefined → Anthropic**
- Header `anthropic-version: 2026-10-21`
- Body **JSON**: `{{ JSON.stringify($json.anthropicRequest) }}`, Timeout 300000
- **Settings: On Error → Continue; Retry On Fail: on, 3 tries, 5,000 ms.** A network blip must not cost the run its explanations, and a failure must still reach the check.

### Step 14. `Check explanations` (Code)
Paste [`code/2-check-explanations.js`](workflows/code/2-check-explanations.js). **The model proposes; the code decides.** It handles API errors, refusals and cut-off answers, then for each new incident checks: exactly one explanation; **evidence ids that Claude was shown** (record ids or ids quoted in the detail text); related rules that actually failed; no empty fields. Failures get a plain fallback (`explanation_ok: false`) and a line in `problems`. It also computes tokens and cost.

**Test:** `node evaluation/test-check-explanations.js` replays a real Claude response through this exact file and tries an invented id, a bad rule link, a missing explanation, a refusal and an API error.

### Step 15. `No new failures` (Code) and `Save explanations` (Postgres)
`No new failures` ([`code/3-no-new-failures.js`](workflows/code/3-no-new-failures.js)) returns the same shape as the check, with no explanations and zero cost. Connect **both** to `Save explanations`:
```sql
SELECT dq.save_explanations($1::jsonb) AS saved
```
Query Parameters: `{{ [ JSON.stringify($json.explanations) ] }}`

---

## Part E. Jira (Steps 16–19)

`Save explanations` has **two** outputs connections: Jira (this part) and Finish (Part F). **Place the Jira nodes higher on the canvas.** In execution order v1, n8n runs the upper branch to the end first, so the run summary already contains the new ticket keys.

### Step 16. `Plan Jira updates` (Code)
Paste [`code/4-plan-jira-updates.js`](workflows/code/4-plan-jira-updates.js). One item per change: **new** → a Bug (summary `[DQ][severity] rule: N record(s) in table`, the checked explanation, an evidence table, the SQL in a code block, labels `data-quality` and `dq-<rule>`); **ongoing** → a comment with the new count; **resolved** → a comment that the check passes again. Returns nothing when `jiraEnabled` is off.

### Step 17. `Update Jira` (HTTP Request)
**POST** `{{ $json.url }}`, Authentication **Predefined → Jira SW Cloud API**, body `{{ JSON.stringify($json.body) }}`. On Error → Continue, Retry On Fail 3 × 5,000 ms.

### Step 18. `Collect Jira keys` (Code)
Paste [`code/5-collect-jira-keys.js`](workflows/code/5-collect-jira-keys.js): pairs each response with its request (`pairedItem`) and keeps the keys of new tickets.

### Step 19. `Remember Jira keys` (Postgres)
```sql
SELECT dq.record_jira($1::jsonb) AS saved
```
Query Parameters: `{{ [ JSON.stringify($json.keys) ] }}`. The next run comments on these tickets instead of opening new ones.

**Test:** run twice on the same data. The first run creates 16 tickets; the second only comments (http://localhost:8089/_state).

---

## Part F. Finish, notify, respond (Steps 20–24)

### Step 20. `Finish run` (Postgres)
```sql
SELECT dq.finish_run($1::int, $2::jsonb) AS summary
```
Query Parameters:
```
{{ [ $('Plan explanations').first().json.runId, JSON.stringify(($('Check explanations').isExecuted ? $('Check explanations') : $('No new failures')).first().json.usage) ] }}
```
`.isExecuted` picks whichever branch ran.

### Step 21. `Format response` (Code)
Paste [`code/6-format-response.js`](workflows/code/6-format-response.js): the API response (counts, failures with ids and explanations, problems, cost) and a short chat message.

### Step 22. `Post to chat?` (If) → `Post to Slack` (HTTP Request)
Condition `{{ !!$('Settings').first().json.slackWebhookUrl }}`; POST `{ text: $json.chat_text }` to the webhook URL. Skipped when the URL is empty.

### Step 23. `Called by API?` (If)
Condition `{{ $('Run via API').isExecuted }}`, so scheduled runs don't try to answer a request that never came.

### Step 24. `Respond with summary` (Respond to Webhook)
Respond With **JSON**, body `{{ JSON.stringify($('Format response').first().json) }}`.

---

## Part G. The report page (Steps 25–28)

### Step 25. `Report page` (Webhook)
**GET**, path `dq/report`, Respond **Using 'Respond to Webhook' node**.

### Step 26. `Load report` (Postgres)
```sql
SELECT dq.report(14, NULLIF($1, '')::int) AS report
```
Query Parameters: `{{ [ String($json.query?.run ?? '').replace(/[^0-9]/g, '') ] }}`. `?run=N` shows an earlier run; anything that isn't a number is ignored.

### Step 27. `Build report page` (Code)
Paste [`code/7-build-report-page.js`](workflows/code/7-build-report-page.js): KPIs, every rule's status by table, the failures with their explanations and evidence, resolved incidents, and a bar per recent run. Every value is HTML-escaped.

### Step 28. `Return report page` (Respond to Webhook)
Respond With **Text**, body `{{ $json.html }}`, header `Content-Type: text/html; charset=utf-8`.

**Test:** open http://localhost:5678/webhook/dq/report.

---

## Part H. Evaluate (Steps 29–31)

### Step 29. Rule edge cases
`psql -d contoso_dq -v ON_ERROR_STOP=1 -f evaluation/rule-edge-cases.sql` on clean data. Boundary tests in a rolled-back transaction: a partial current day, a day with zero transactions, the fee boundaries (16.67 → 0.25, 1,000.00 → 15.00, 33.33 → 0.50), and a duplicate email in a different case.

### Step 30. Guardrail tests
`node evaluation/test-check-explanations.js`: the explanation check against a real Claude response. No API call.

### Step 31. The full evaluation
```bash
python evaluation/evaluate.py --url http://localhost:5678/webhook/dq/run --pg-container dq-postgres --pg-user <user>
```
Three live runs (defects, the same data again, clean data) graded against the answer key, plus the two test suites above: 10 gates, exit code 1 if any fails. One run calls Claude (about $0.15).

---

## Concepts worth understanding

- **Deterministic detection, AI explanation.** Whether data is wrong is a fact a query can establish; why it is wrong is a judgement. Mixing the two makes the monitor unauditable. Here the AI can't change a result, a severity or a record.
- **Verify the model's claims you can verify.** Evidence ids and related rules are checkable, so they are checked. Free-text causes can't be checked automatically, so they are labelled as AI-written and graded in the evaluation.
- **Incidents, not alerts.** State (open, ongoing, resolved) in the database turns a stream of alerts into a small number of tickets with a history.
- **Plant defects to measure a monitor.** A monitor that has never been shown a known problem can't be trusted to find an unknown one. Clean data is the other half: it measures false alarms.
- **Test the guardrail with real model output.** The first version of the check was too strict; only a real response showed it. Keep such responses as fixtures.

## Common mistakes

| Mistake | Effect |
|---|---|
| Database time zone not UTC | Ledger and volume rules fail on almost every row |
| Jira branch placed below the Finish branch | The run summary has no Jira keys (they are saved afterwards) |
| `Explain failures` without *On Error → Continue* | A Claude outage stops the run before incidents are saved and Jira is updated |
| Putting names or emails in a rule's detail | Personal data is sent to the AI service |
| Rule SQL whose first column isn't the record id | Wrong ids in the results and tickets: put the id first, then the detail |
| Judging a volume rule on test data with no "today" | The partial-day bug stays hidden; test with `rule-edge-cases.sql` |

---
Part of [AI Workflow Automation](../../README.md) by **Trevor Kauyu**.
