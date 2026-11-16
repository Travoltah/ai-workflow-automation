# Build guide: KYC document review

This guide builds the workflow part by part. To only run it, import `workflows/01-kyc-document-review.json` and follow the [README](README.md).

You need about **3 hours**. The SQL is in [`init-db/`](init-db/), the intake service in [`service/`](service/), and every Code node's script in [`workflows/code/`](workflows/code/).

## Contents
- [What you will build](#what-you-will-build)
- [Part A. The database (Steps 1–2)](#part-a-the-database-steps-12)
- [Part B. The intake service (Steps 3–7)](#part-b-the-intake-service-steps-37)
- [Part C. Specimen documents (Step 8)](#part-c-specimen-documents-step-8)
- [Part D. The workflow: entry points (Steps 9–10)](#part-d-the-workflow-entry-points-steps-910)
- [Part E. Submit and intake (Steps 11–13)](#part-e-submit-and-intake-steps-1113)
- [Part F. Read with Claude, check in code (Steps 14–18)](#part-f-read-with-claude-check-in-code-steps-1418)
- [Part G. Checks and response (Steps 19–20)](#part-g-checks-and-response-steps-1920)
- [Part H. Review, passwords and decisions (Steps 21–24)](#part-h-review-passwords-and-decisions-steps-2124)
- [Part I. Test (Steps 25–27)](#part-i-test-steps-2527)
- [Concepts worth understanding](#concepts-worth-understanding)
- [Common mistakes](#common-mistakes)

---

## What you will build

```
POST kyc/submit ──┐                        ┌─(0) Read submission ─> Create application ─> One item per upload ─> Intake document ─> Intake results ─┐
POST kyc/process ─┼─> Settings ─> Route ───┼─(1) Read process request ─────────────────────────────────────────────────────────────────────────────┤
GET  kyc/review ──┤                        │    Documents to read ─> One item per document to read ─> Anything to read? <──────────────────────────┘
POST kyc/decide ──┘                        │       yes ─> Get page images ─> Build extraction request ─> Extract with Claude ─> Check extractions ─┐
                                           │       no ──> Nothing to read ─────────────────────────────────────────────────────────────────────┤
                                           │    Save extractions <──────────────────────────────────────────────────────────────────────────────┘
                                           │    ─> Run checks (intake service) ─> Format result ─> Respond
                                           ├─(2) Load review queue ─> Build review page ─> Return review page
                                           └─(3) Read decision ─> Record decision ─> Decision response ─> HTML or JSON
Reviewer's browser ── password form ──> intake service /unlock ──> POST kyc/process      (passwords never pass through n8n)
```

---

## Part A. The database (Steps 1–2)

### Step 1. Schema
[`01-schema.sql`](init-db/01-schema.sql): `applications`, `documents` (the original file, status, encryption, attempt counter, digital text, PDF metadata), `pages` (an image for the model and a thumbnail for the reviewer), `extractions`, `checks`, `audit_log`, `settings`. Functions: `create_application`, `docs_to_read`, `save_extractions`, `review_queue`, and `decide` (a decision is made once; only an application that is `ready_for_review` can be approved).

### Step 2. Policy settings
[`02-settings.sql`](init-db/02-settings.sql): minimum age, proof-of-address age, password attempts, ID number formats per `COUNTRY:doc_type`, and the PDF tools that issuers don't use (Photoshop, online PDF editors…). Policy lives in data, not code.

---

## Part B. The intake service (Steps 3–7)

Everything about a file is decided here, in code, before any AI sees it.

### Step 3. What a file really is
[`intake.py`](service/intake.py) `inspect()`: the type comes from the file's bytes (`filetype`); an OLE container is either an encrypted Office file or an old .doc/.xls (`msoffcrypto-tool`); a ZIP is only treated as Word if it has `word/document.xml`, and one containing `vbaProject.bin` (macros) is rejected.

### Step 4. Passwords
PyMuPDF's `needs_pass` separates a PDF that **needs a password to open** from one that only **restricts** printing or copying. Without a password: `needs_password`. With one: `authenticate()` once; a wrong password returns `wrong_password`. Office files: `msoffcrypto` `load_key` + `decrypt`, in memory.

### Step 5. Pages and quality
Images are turned upright with `ImageOps.exif_transpose`, HEIC opens through `pillow-heif`, TIFF frames are split, PDF pages are rendered (≤1,568 px for the model, ≤900 px thumbnails). Quality is scored **on content tiles only** (50 px tiles with real contrast): blur = 90th percentile of the Laplacian variance, glare = blown-out pixels in content (photos only), plus brightness and resolution. All pages failing → `poor_quality` with a reason the customer can act on.

### Step 6. The MRZ
[`mrz.py`](service/mrz.py): ICAO 9303 TD3 parsing and check digits (weights 7-3-1, `<` = 0, A = 10 … Z = 35) for the document number, date of birth, expiry, personal number and the composite. Tested against the ICAO specimen passport.

### Step 7. The checks
[`validation.py`](service/validation.py) `validate()`: pure functions. Files the customer must fix; wrong or missing documents; ID expiry, age, number format, MRZ check digits and MRZ-vs-page; proof-of-address age; name, date of birth and address against the application; PDF edit signals (warnings only). Status: `processing` (documents still to read), `action_required` (the customer must act) or `ready_for_review`. Never `approved`.

**Test:** `docker compose run --rm intake python -m pytest -q tests` (27 tests).

The API ([`app.py`](service/app.py)): `/intake`, `/documents/{id}/ai-input`, `/validate/{app}`, `/unlock`. In `/unlock` the password exists only in a local variable for one attempt, and the call back to n8n runs in a worker thread (a blocking call deadlocks: n8n calls this service back).

---

## Part C. Specimen documents (Step 8)

[`make_specimens.py`](scripts/make_specimens.py) draws Utopia passports (with valid MRZs from `build_td3`) and national ID cards, writes bills and statements as PDFs, and makes the variants: blurred, saved sideways with an EXIF tag, scanned (image-only PDF), HEIC, password-protected (AES-256), edited MRZ, Photoshop metadata, a renamed text file, a macro .docm. It writes `cases.json` with the true field values and the expected outcome per application.

---

## Part D. The workflow: entry points (Steps 9–10)

### Step 9. Four webhooks → `Settings`
`POST kyc/submit`, `POST kyc/process`, `GET kyc/review`, `POST kyc/decide`, each **Respond: Using 'Respond to Webhook' node**, all into `Settings` (Include Other Input Fields: on) with `model`, `serviceUrl`, `reviewUrl`, `decideUrl`, `unlockUrl`.

**Workflow settings:** Execution order **v1**; **Save successful / failed production executions: Do not save**; save manual executions: off. ID images pass through these nodes.

### Step 10. `Route` (Switch, expression mode, 4 outputs)
```
{{ (u => u.includes('/kyc/process') ? 1 : u.includes('/kyc/review') ? 2 : u.includes('/kyc/decide') ? 3 : 0)(String($json.webhookUrl || '')) }}
```

---

## Part E. Submit and intake (Steps 11–13)

### Step 11. `Read submission` (Code) → `Create application` (Postgres)
[`1-read-submission.js`](workflows/code/1-read-submission.js) checks the request's shape. Then `SELECT kyc.create_application($1, $2::jsonb) AS application_id` with `{{ [ $json.reference, JSON.stringify($json.applicant) ] }}`.

### Step 12. `One item per upload` → `Intake document` (HTTP Request)
[`2-one-item-per-upload.js`](workflows/code/2-one-item-per-upload.js); POST `{{ $('Settings').first().json.serviceUrl }}/intake` with the application id, filename, declared type and base64 data. On Error → Continue.

### Step 13. `Intake results` (Code) / `Read process request` (Code)
[`3-intake-results.js`](workflows/code/3-intake-results.js) collects the statuses; [`4-read-process-request.js`](workflows/code/4-read-process-request.js) is the `kyc/process` entry. Both lead to Part F.

---

## Part F. Read with Claude, check in code (Steps 14–18)

### Step 14. `Documents to read` (Postgres, **Execute Once**)
`SELECT kyc.docs_to_read($1::int) AS docs` with the application id from whichever entry ran:
`{{ [ ($('Intake results').isExecuted ? $('Intake results') : $('Read process request')).first().json.application_id ] }}`

### Step 15. `One item per document to read` → `Anything to read?`
[`5-one-item-per-document.js`](workflows/code/5-one-item-per-document.js) returns one item per readable document, or a single `skip` item. If `{{ !$json.skip }}`.

### Step 16. `Get page images` → `Build extraction request`
GET `…/documents/{{ $json.document_id }}/ai-input`. [`6-build-extraction-request.js`](workflows/code/6-build-extraction-request.js): the page images and any digital text, and a schema with the document type, readability, notes and 15 fields, each `{value, as_printed, confidence}`. Values are **plain strings with `""` for "absent"**: structured outputs allow at most 16 nullable fields.

### Step 17. `Extract with Claude` (HTTP Request)
POST `https://api.anthropic.com/v1/messages`, Anthropic credential, header `anthropic-version: 2026-10-21`, body `{{ JSON.stringify($json.anthropicRequest) }}`, batching 4 / 1,000 ms, On Error → Continue, Retry 3 × 5,000 ms.

### Step 18. `Check extractions` / `Nothing to read` → `Save extractions`
[`7-check-extractions.js`](workflows/code/7-check-extractions.js): `""` → null; impossible dates dropped; on digital documents the name, address, issuer and date must be in the file's own text; **a failed, refused or cut-off call stores nothing**; tokens and cost per document. Then `SELECT kyc.save_extractions($1::jsonb)`.

**Test:** `node evaluation/test-check-extractions.js` (11 tests on real Claude responses).

---

## Part G. Checks and response (Steps 19–20)

### Step 19. `Run checks` (HTTP Request, Execute Once)
POST `…/validate/{{ application id }}`: the intake service runs [`validation.py`](service/validation.py), stores the checks and sets the status.

### Step 20. `Format result` → `Respond with result`
[`9-format-result.js`](workflows/code/9-format-result.js): status, customer actions, checks, AI calls and cost.

---

## Part H. Review, passwords and decisions (Steps 21–24)

### Step 21. `Load review queue` → `Build review page` → `Return review page`
`SELECT kyc.review_queue(30, NULLIF($1, '')) AS queue` with `{{ [ String($json.query?.ref ?? '').slice(0, 60) ] }}`. [`10-build-review-page.js`](workflows/code/10-build-review-page.js): images beside the fields read, every check, what the customer must fix, and the decision form.

### Step 22. The password form
For a `needs_password` document the page shows a form whose `action` is the **intake service's** `/unlock` (`unlockUrl`), with `autocomplete="off"` and `type="password"`. n8n never receives it. After a successful unlock the service calls `POST kyc/process`.

### Step 23. `Read decision` → `Record decision`
[`11-read-decision.js`](workflows/code/11-read-decision.js); `SELECT kyc.decide($1::int, $2, $3, $4) AS result`.

### Step 24. `Decision response` → HTML or JSON
[`12-decision-response.js`](workflows/code/12-decision-response.js) and an If on `{{ $json.fromForm }}`.

---

## Part I. Test (Steps 25–27)

25. `docker compose run --rm intake python -m pytest -q tests`
26. `node evaluation/test-check-extractions.js`
27. `python evaluation/evaluate.py …` (README): 12 specimen applications, the password flow, a search for the password in the KYC database and n8n's execution data, and the decision rules. About $0.60.

---

## Concepts worth understanding

- **Decide what a file is before the AI sees it.** Type, encryption, macros and quality are facts code can establish; it's cheaper, safer and explainable.
- **Let arithmetic catch what the eye misses.** MRZ check digits turn "does this look edited?" into a calculation.
- **Measure quality where the content is.** Averages over a page penalise documents for having margins.
- **A failure is not an answer.** When the AI call fails, store nothing; never let an outage look like a finding about the customer.
- **Keep secrets out of the orchestrator.** Workflow tools log inputs; route passwords around them.
- **Advisory AI notes can be wrong.** Decisions rest on checks and people.

## Common mistakes

| Mistake | Effect |
|---|---|
| Leaving execution saving on | Every ID image and form is kept in n8n's database |
| Posting the password form to n8n | The password lands in execution data |
| A blocking HTTP call inside an async endpoint that is called back | Deadlock until timeout |
| Nullable fields everywhere in the schema | The API rejects schemas with more than 16 union-typed fields |
| Storing a fallback "other" when the AI call fails | The customer is told they uploaded the wrong document |
| Tuning quality thresholds on synthetic images only | Real uploads are rejected or let through; tune on real samples in a secure environment |

---
Part of [AI Workflow Automation](../../README.md) by **Trevor Kauyu**.
