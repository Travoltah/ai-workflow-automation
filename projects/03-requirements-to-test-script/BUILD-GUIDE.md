# Build guide: requirements to Jira stories, QA tickets and an Excel test script

This guide builds the whole workflow by hand in the n8n editor, node by node, so you understand every part. If you only want to run it, import `workflows/01-requirements-to-test-script.json` and follow the [README](README.md) instead.

You need about **2–3 hours**. Every Code node's script is in [`workflows/code/`](workflows/code/): you paste it, you don't type it. This guide explains what each one does.

## Contents
- [What you will build](#what-you-will-build)
- [Before you start](#before-you-start)
- [Part A. The test-script service (Steps 1–3)](#part-a-the-test-script-service-steps-13)
- [Part B. Inputs (Steps 4–7)](#part-b-inputs-steps-47)
- [Part C. Requirements analysis (Steps 8–11)](#part-c-requirements-analysis-steps-811)
- [Part D. Jira stories (Steps 12–18)](#part-d-jira-stories-steps-1218)
- [Part E. Test cases (Steps 18–22)](#part-e-test-cases-steps-1822)
- [Part F. QA tickets (Steps 23–28)](#part-f-qa-tickets-steps-2328)
- [Part G. Excel and replies (Steps 29–33)](#part-g-excel-and-replies-steps-2933)
- [Part H. Test, publish and export (Steps 34–37)](#part-h-test-publish-and-export-steps-3437)
- [Concepts worth understanding](#concepts-worth-understanding)
- [Common mistakes](#common-mistakes)

---

## What you will build

```
Upload requirements (form) ─┐
                            ├─ Settings ─ Collect inputs ─ Read files ─ Build analysis request ─ Analyse documents?
Run via API (webhook) ──────┘                                                                        │yes        │no
                                                                       Analyse requirements ─ Read analysis    │
                                                                                                  └─ Look for earlier runs? ─┘
                                                                                     │yes                        │no
                     Find stories from earlier runs ─ Earlier stories found? ─┬ yes ─ Build match request ─ Match earlier stories ─┐
                                                                              └ no ─────────────────────────────────────────────────┴─ Plan stories ┘
 Plan stories ─ Story route ─┬ create ─ Create Jira story ─ Remember story key ─┐
                             ├ fetch ── Get Jira story ──── Read Jira story ────┼─ All stories (Merge)
                             └ other ───────────────────────────────────────────┘
 All stories ─ Prepare stories ─ Build test request ─ Write test cases ─ Check test cases ─ Lay out test script
 Lay out test script ─ QA ticket route ─┬ create ── Create QA ticket ─ Link QA ticket to story ─ Remember QA ticket ─┐
                                        ├ comment ─ Comment on QA ticket ─ Remember QA comment ───────────────────────┼─ All QA tickets (Merge)
                                        └ none ───────────────────────────────────────────────────────────────────────┘
 All QA tickets ─ Collect results ─ Build Excel test script ─ Reply to ─┬ Form ─ Download test script
                                                                        └ API ── Return test script
```

**38 working nodes** plus 4 sticky notes. Three ideas carry the design:

1. **One shape for every story.** A story from the document, from Jira or from an earlier run looks the same after `Prepare stories`, so the test-case part never needs to know where it came from.
2. **Decide first, then act.** `Plan stories` and `Lay out test script` decide what happens to each story (create, reuse, read, comment). The Jira nodes after them only carry out those decisions. That makes "never recreate" easy to check.
3. **Errors are data.** Jira nodes continue on error. The next Code node records what went wrong, and the Excel and completion page report it. One bad issue type doesn't lose you the whole run.

---

## Before you start

- Docker Desktop, an Anthropic API key, and this folder.
- Start the stack with the mock Jira, so you can test every branch without a Jira site:
  ```bash
  cp .env.example .env              # set N8N_ENCRYPTION_KEY
  docker compose --profile demo up -d --build
  ```
- Open http://localhost:5678 and create the owner account. Create a new, empty workflow called **Req2Test · Requirements to Jira stories, QA tickets and Excel test script**.
- Workflow **Settings** (⋯ menu → Settings): *Execution order* **v1** (the default for new workflows).
- **Credentials** (Overview → Credentials → Create):
  - **Anthropic**: your API key.
  - **Jira SW Cloud API**: for the mock, e-mail `demo@example.com`, token `mock-token`, domain `http://mock-jira:8089`. For your Jira: your e-mail, an API token from id.atlassian.com → Security, and `https://<site>.atlassian.net`.

> **Tip.** Every node has a name in `code font` below. Use exactly these names: Code nodes refer to other nodes by name, for example `$('Collect inputs')`.

---

## Part A. The test-script service (Steps 1–3)

n8n is excellent at orchestration but has no built-in way to read Word files with their tables and pictures, or to write a formatted Excel with formulas, drop-downs and colours. A small Python service does those two jobs. It runs in the same Docker network as n8n, has no published port, and holds no keys.

### Step 1. Read the service code
Open [`service/app.py`](service/app.py). It has two endpoints:

| Endpoint | In | Out |
|---|---|---|
| `POST /prepare` | `{ files: [{ name, mimeType, data (base64), role }], figmaUrls, maxImages }` | `{ blocks, files, warnings, imagesUsed }`: content blocks ready for the Claude Messages API |
| `POST /excel` | the test-script JSON built in step 30 | the `.xlsx` file (also saved in `output/`) |

[`service/document_reader.py`](service/document_reader.py) decides per file:
- **PDF** → a `document` block. Claude reads PDFs natively, including tables and diagrams, so nothing is lost.
- **DOCX** → the text in document order, headings as Markdown `#`, tables as Markdown tables, **plus every embedded picture** (FSDs often contain screenshots). Pictures smaller than 120 px (logos, icons) are skipped.
- **Images** → scaled to at most 1568 px on the long edge (the size Claude uses) and sent as `image` blocks.
- **Figma link** → exported to PNG through the Figma API with `FIGMA_TOKEN` from `.env`.
- Anything else → a **warning**, not an error.

[`service/excel_builder.py`](service/excel_builder.py) writes the workbook. Its docstring lists every sheet.

### Step 2. Run the unit tests
```bash
docker compose run --rm -v "$PWD/sample-input:/samples:ro" -v "$PWD/service:/app" -w /app --user root \
  testscript-service sh -c "pip install -q pytest && python -m pytest -q tests"
```
Expect `8 passed`. The tests check that the sample CR keeps its headings, tables and embedded wireframe, that images are limited, that the Summary formulas point at the right sheets, and that Figma links are parsed.

### Step 3. Check n8n can reach it
In any workflow, add an **HTTP Request** node: GET `http://testscript-service:8000/health` → **Execute step**. Expect `{"status":"ok"}`. Delete the node.

---

## Part B. Inputs (Steps 4–7)

### Step 4. Form trigger: `Upload requirements`
Add **n8n Form Trigger** (*On form submission*).

| Setting | Value |
|---|---|
| Form Title | `Requirements to test script` |
| Form Description | `Upload an FSD or Change Request and any wireframes, or enter existing Jira stories. You get Jira stories, linked QA tickets and an Excel test script.` |
| Respond When | *Workflow Finishes* is set for you once you add the Form Ending in step 32 |

Form elements (in this order; the names matter, the Code node reads them):

| Field Name | Element Type | Settings |
|---|---|---|
| `Requirements documents` | File | Multiple Files **on** · Accepted File Types `.pdf, .docx, .txt, .md` |
| `Wireframes` | File | Multiple Files **on** · Accepted File Types `.png, .jpg, .jpeg, .gif, .webp, .pdf` |
| `Figma link` | Text | Placeholder `https://www.figma.com/design/...?node-id=12-34 (optional)` |
| `Existing Jira stories` | Text | Placeholder `e.g. CPAY-12, CPAY-14. These are read, not recreated` |
| `Jira project key` | Text | Placeholder `Where new stories go, e.g. CPAY` |
| `Create Jira tickets` | Dropdown | Options `Yes: create stories and linked QA tickets` and `No: only build the Excel test script` · Required **on** |
| `System name` | Text | optional |
| `Test ID prefix` | Text | optional |

Options → **Button Label** `Generate test script`.

> **How uploads arrive.** Each file becomes a *binary* property named after the field: `Requirements_documents_0`, `Wireframes_0`, `Wireframes_1` and so on (spaces become `_`, and a number is added because multiple files are allowed). The Code node in step 7 relies on the `Wireframes` prefix.

### Step 5. API trigger: `Run via API`
Add **Webhook**.

| Setting | Value |
|---|---|
| HTTP Method | `POST` |
| Path | `req2test/run` |
| Respond | *When Last Node Finishes* |
| Response Data | *First Entry Binary* |
| Put Output File in Field | `testScript` |

The API takes JSON with base64 files (`documents`, `wireframes`) and the same options as the form (see the README). It answers with the Excel file.

### Step 6. `Settings` (Edit Fields)
Add **Edit Fields (Set)** after **both** triggers (connect both to its input).

- Mode: *Manual Mapping* · **Include Other Input Fields: on** (so the form answers and the uploaded files pass through).
- Fields (all *String*):

| Name | Value |
|---|---|
| `jiraBaseUrl` | `http://mock-jira:8089` (later your `https://<site>.atlassian.net`) |
| `jiraProjectKey` | empty, or your default project |
| `storyIssueType` | `Story` |
| `qaIssueType` | `Task` |
| `qaLinkType` | `Relates` |
| `defaultTestIdPrefix` | `TC` |
| `model` | `claude-opus-5-5` |
| `serviceUrl` | `http://testscript-service:8000` |

Everything a user might change lives here, in one place, instead of inside ten nodes.

### Step 7. `Collect inputs` (Code)
Add **Code** · Mode **Run Once for All Items** · paste [`code/1-collect-inputs.js`](workflows/code/1-collect-inputs.js).

What it does:
- Detects the channel with `$('Upload requirements').isExecuted`.
- Reads every uploaded file with `await this.helpers.getBinaryDataBuffer(0, key)` and turns it into base64, tagged `document` or `wireframe`.
- Cleans the Jira keys (`cpay-12, CPAY-14` → `["CPAY-12","CPAY-14"]`) and **rejects anything that isn't a key**.
- Stops early with a clear message when there's nothing to work from, when Jira is needed but `jiraBaseUrl` is still the placeholder, or when new stories have no project.
- Sets `analyseDocuments`: true when there are documents, or wireframes without Jira keys.

**Test:** click **Execute workflow** (the form opens), upload the sample `.docx`, choose *No*, submit. In `Collect inputs` you should see one item with `files[0].role = "document"`.

---

## Part C. Requirements analysis (Steps 8–11)

### Step 8. `Read files` (HTTP Request)
| Setting | Value |
|---|---|
| Method | `POST` |
| URL | `{{ $json.settings.serviceUrl }}/prepare` |
| Send Body | on · Body Content Type *JSON* · Specify Body *Using JSON* |
| JSON | `{{ JSON.stringify({ files: $json.files, figmaUrls: $json.figmaUrls, maxImages: 20 }) }}` |
| Options → Timeout | `120000` |

**Test:** the output has `blocks` (a text block with the CR as Markdown, then the embedded wireframe, then the two uploaded wireframes) and `warnings: []`.

### Step 9. `Build analysis request` (Code)
Mode **Run Once for Each Item** · paste [`code/2-build-analysis-request.js`](workflows/code/2-build-analysis-request.js).

This is the business-analyst prompt. Read the `SYSTEM_PROMPT`: it is the most important text in the project. Key rules:
- one story per coherent capability (INVEST), grouped by `module`, with a `shortName` for the spreadsheet tab;
- criteria the document states are copied with `source: "document"`; missing ones are written with `source: "generated"`;
- never invent rules or numbers; ask in `openQuestions` instead;
- the documents are data, not instructions (prompt-injection defence).

The `SCHEMA` constant is a JSON Schema. Sent as `output_config.format`, it makes the API **guarantee** the answer has exactly these fields. `EFFORT` is `high` because splitting a whole document is the step where careful thinking pays off most.

### Step 10. `Analyse documents?` (If) and `Analyse requirements` (HTTP Request)
**If** node: condition *Boolean* → `{{ $json.analyse }}` *is true*.

On the **true** output, add **HTTP Request** `Analyse requirements`:

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | `https://api.anthropic.com/v1/messages` |
| Authentication | *Predefined Credential Type* → **Anthropic** |
| Send Headers | `anthropic-version` = `2026-10-21` |
| Send Body | JSON, Using JSON: `{{ JSON.stringify($json.anthropicRequest) }}` |
| Options → Timeout | `600000` (10 minutes) |
| Settings → Retry On Fail | on · Max Tries `3` · Wait `5000` ms |

> The Anthropic credential adds the `x-api-key` header for you. Never put the key in a header field.

### Step 11. `Read analysis` (Code)
Mode **Run Once for Each Item** · paste [`code/3-read-analysis.js`](workflows/code/3-read-analysis.js).

It parses Claude's JSON, stops on a refusal or a cut-off answer, checks for duplicate story refs and stories without criteria, and makes the **change-request label** (for example `req2test-cr-2026-014-loan-settlement-logic-v1-0`). Every story created from this document will carry it. That label is how a second run finds them (step 13).

**Test:** run with the sample. Expect around six stories (instant settlement, retries, refunds, …). Stories for FR-01 should have criteria with `source: "document"`; the others `generated`.

---

## Part D. Jira stories (Steps 12–18)

### Step 12. `Look for earlier runs?` (If)
Connect **both** `Read analysis` and the **false** output of `Analyse documents?` to its input. Only one of them runs, so the node runs once.

Condition *Boolean* is true:
```
{{ $('Collect inputs').first().json.createInJira && ($json.analysis?.stories?.length ?? 0) > 0 }}
```

### Step 13. `Find stories from earlier runs` (HTTP Request)
On the **true** output.

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | `{{ $('Collect inputs').first().json.settings.jiraBaseUrl }}/rest/api/3/search/jql` |
| Authentication | *Predefined Credential Type* → **Jira SW Cloud API** |
| Body (JSON) | `{{ JSON.stringify({ jql: 'project = "' + $('Collect inputs').first().json.projectKey + '" AND labels = "' + $json.crLabel + '" ORDER BY created ASC', fields: ['summary', 'labels', 'issuelinks'], maxResults: 100 }) }}` |
| Settings → On Error | *Continue* |

> `/rest/api/3/search/jql` is Jira Cloud's current search endpoint. The older `/rest/api/2/search` is being retired.

### Step 13b. `Earlier stories found?`, `Build match request` and `Match earlier stories`
Claude words a story a little differently every time, so a second run can't recognise its earlier stories by title. When the search finds stories, Claude compares them by **scope** instead:

1. **If** `Earlier stories found?`: Boolean true `{{ ($json.issues ?? []).length > 0 }}`.
2. On **true**, **Code** `Build match request`, Each Item, [`code/4a-build-match-request.js`](workflows/code/4a-build-match-request.js). It lists the existing keys and summaries and the new stories, and asks for `{ matches: [{ ref, existingKey }] }`, with each existing key used at most once. Effort `low`, because this is a quick comparison.
3. **HTTP Request** `Match earlier stories`: the same settings as `Analyse requirements` (step 10).

`Plan stories` checks the answer in code: only keys that really exist, each used once. If the matching call fails, identical titles are still recognised.

### Step 14. `Plan stories` (Code)
Connect `Match earlier stories`, the **false** output of `Earlier stories found?` **and** the false output of `Look for earlier runs?`. Only one of them runs. Mode **Run Once for All Items** · paste [`code/4-plan-stories.js`](workflows/code/4-plan-stories.js).

It outputs **one item per story** with an `action`:

| action | When | Then |
|---|---|---|
| `create` | a document story not yet in Jira | build `jiraCreateBody` (summary, wiki-markup description, labels) |
| `reuse` | an earlier run of this document already created this story (matched in step 13b) | keep its key, **create nothing** |
| `fetch` | a key the user typed | read it from Jira, **create nothing** |
| `preview` | *Create Jira tickets* is No | no Jira at all |

The description puts **acceptance criteria last**, under `h3. Acceptance criteria`, so that if you later type this story's key, step 17 reads the criteria back. Generated criteria are marked *(generated)*. Each item also gets a `seq` number so the original order can be restored after the branches join.

### Step 15. `Story route` (Switch)
Mode *Rules*:

| Output | Rule |
|---|---|
| `create` | `{{ $json.action }}` *is equal to* `create` (Rename Output on) |
| `fetch` | `{{ $json.action }}` *is equal to* `fetch` |

Options → **Fallback Output** *Extra Output* (this third output carries `reuse` and `preview`).

### Step 16. `Create Jira story` + `Remember story key`
**HTTP Request** on output `create`:

| Setting | Value |
|---|---|
| Method / URL | `POST` `{{ $('Collect inputs').first().json.settings.jiraBaseUrl }}/rest/api/2/issue` |
| Authentication | Jira SW Cloud API |
| Body (JSON) | `{{ JSON.stringify($json.jiraCreateBody) }}` |
| Settings → On Error | *Continue* |

Then **Code** `Remember story key`, Each Item, [`code/5-remember-story-key.js`](workflows/code/5-remember-story-key.js). It joins the new key to the story with `$('Plan stories').item` (n8n's *paired items*: every output item knows which input item produced it), or records Jira's error.

> **Why API v2 here?** v2 accepts the description as wiki-markup text. v3 needs Atlassian Document Format (a JSON tree). Both are current for creating issues.

### Step 17. `Get Jira story` + `Read Jira story`
**HTTP Request** on output `fetch`: GET
```
{{ $('Collect inputs').first().json.settings.jiraBaseUrl }}/rest/api/2/issue/{{ $json.jiraKey }}?fields=summary,description,issuetype,status,priority,labels,components,issuelinks
```
Jira credential · On Error *Continue*.

Then **Code** `Read Jira story`, Each Item, [`code/6-read-jira-story.js`](workflows/code/6-read-jira-story.js). It finds the *Acceptance criteria* section in the description (Markdown, wiki or plain text; or a custom field via `AC_CUSTOM_FIELD`) and returns the same shape as a document story. `issuelinks` is kept: step 23 uses it to spot an existing QA ticket.

### Step 18. `All stories` (Merge) and `Prepare stories` (Code)
**Merge**: Mode *Append* · **Number of Inputs 3**. Connect `Remember story key` → input 1, `Read Jira story` → input 2, the Switch's fallback output → input 3.

> In *Append* mode the Merge node needs only **one** input with data. That's what makes it safe here: a run with only typed keys sends nothing to inputs 1 and 3.

Then **Code** `Prepare stories`, All Items, [`code/7-prepare-stories.js`](workflows/code/7-prepare-stories.js): restores the original order by `seq` and sets aside keys that couldn't be read (typos, no permission), so the run continues with the rest.

---

## Part E. Test cases (Steps 19–22)

### Step 19. `Build test request` (Code)
Each Item · [`code/8-build-test-request.js`](workflows/code/8-build-test-request.js).

The QA prompt is written for **your test-script columns**: `module` (Function / Module), `type` (Functional, Negative, Boundary, Integration, Security, Permission, UI, Audit, Regression), `scenario` (Test Scenario), `preconditions`, `testData`, `steps` and `expectedResult`. It also asks for 1–3 **regression** tests per story.

The context includes the change-request summary and the titles of the **other** stories, so Claude doesn't test another story's behaviour here. When no document was analysed (typed keys plus wireframes), the wireframes are sent with every story.

### Step 20. `Write test cases` (HTTP Request)
Same settings as `Analyse requirements` (step 10), plus Options → **Batching**: Items per Batch `4`, Batch Interval `1000` ms.

> The HTTP Request node sends its items **in parallel**. Batching only staggers the start of each group of 4, which is kinder to your API rate limit. Six stories finish in about the time of the slowest one.

### Step 21. `Check test cases` (Code)
Each Item · [`code/9-check-test-cases.js`](workflows/code/9-check-test-cases.js). The **quality gate**, in code rather than in the prompt:
- every criterion is covered by a test; no test points at a criterion that doesn't exist; no given criterion was dropped;
- at least one Negative or Boundary test; no duplicate scenarios; no test without steps or an expected result.

It also labels where each criterion came from: *Document*, *Jira* or *Generated by AI*.

### Step 22. `Lay out test script` (Code)
All Items · [`code/10-lay-out-test-script.js`](workflows/code/10-lay-out-test-script.js).
- Sections **A, B, C…**: one per story, then a final **Regression** section collecting every story's regression tests.
- Test ids **across the whole script**, in sheet order: `SL-001, SL-002, …`. The prefix comes from the form, the document (Claude suggests one, e.g. *SL* for Settlement Logic), or `defaultTestIdPrefix`.
- `Preconditions / Data / Steps` text in the same layout as a manual script: *Preconditions:*, *Test data:*, *Steps:* 1. 2. 3.
- The **QA ticket decision** (`qaAction`) per story, plus the ticket body in Jira wiki markup with a table of the tests and full steps.

**Test:** run in preview mode. You should see one item per story with `rows`, `section` and `qaAction: "none"`.

---

## Part F. QA tickets (Steps 23–28)

### Step 23. `QA ticket route` (Switch)
Rules on `{{ $json.qaAction }}`: output `create` (equals `create`), output `comment` (equals `comment`). Fallback Output *Extra Output* (for `none`).

### Step 24. `Create QA ticket` (HTTP Request)
POST `…/rest/api/2/issue` · Jira credential · Body `{{ JSON.stringify($json.qaCreateBody) }}` · On Error *Continue*.

With `qaIssueType` = `Sub-task`, the body includes `parent: { key: <story> }`, so the ticket sits under the story.

### Step 25. `Link QA ticket to story` (HTTP Request)
POST `{{ $('Collect inputs').first().json.settings.jiraBaseUrl }}/rest/api/2/issueLink` · Jira credential · On Error *Continue* · Options → Response → Response Format **Text** (Jira answers `201` with an empty body, which isn't valid JSON). Body:
```
{{ JSON.stringify({ type: { name: $('Collect inputs').first().json.settings.qaLinkType },
                    inwardIssue: { key: $json.key },
                    outwardIssue: { key: $('Lay out test script').item.json.jiraKey } }) }}
```

### Step 26. `Remember QA ticket` (Code)
Each Item · [`code/11-remember-qa-ticket.js`](workflows/code/11-remember-qa-ticket.js). Keeps the new key, or records whether creating or linking failed.

### Step 27. `Comment on QA ticket` + `Remember QA comment`
On output `comment`: POST `…/rest/api/2/issue/{{ $json.qaKey }}/comment`, Body `{{ JSON.stringify($json.qaCommentBody) }}`, On Error *Continue*. Then **Code** [`code/12-remember-qa-comment.js`](workflows/code/12-remember-qa-comment.js).

This is the second half of "never recreate": a story whose linked issue already starts with `QA: ` gets the regenerated tests as a **comment** on that ticket.

### Step 28. `All QA tickets` (Merge)
Append · 3 inputs: `Remember QA ticket` → 1, `Remember QA comment` → 2, the Switch's fallback → 3.

---

## Part G. Excel and replies (Steps 29–33)

### Step 29. `Collect results` (Code)
All Items · [`code/13-collect-results.js`](workflows/code/13-collect-results.js). Builds the workbook content (`excel`: meta, sections, stories, traceability, questions), estimates the Claude cost from the `usage` of every call, and writes the completion `message`.

### Step 30. `Build Excel test script` (HTTP Request)
| Setting | Value |
|---|---|
| Method / URL | `POST` `{{ $('Collect inputs').first().json.settings.serviceUrl }}/excel` |
| Body (JSON) | `{{ JSON.stringify($json.excel) }}` |
| Options → Response | Response Format **File** · Put Output in Field `testScript` |

The service names the file from the system and change request, for example `Contoso_Lend_CR-2026-014_Loan_Settlement_Logic_V1.0_QA_Test_Script.xlsx`.

### Step 31. `Reply to` (Switch)
Rules on `{{ $('Collect results').first().json.channel }}`: output `Form` (equals `form`), output `API` (equals `api`).

### Step 32. `Download test script` (n8n Form → Form Ending)
| Setting | Value |
|---|---|
| On n8n Form Submission | **Return Binary File** |
| Completion Title | `Your test script is ready` |
| Completion Message | `{{ $('Collect results').first().json.message }}` |
| Input Data Field Name | `testScript` |

The browser shows the summary and downloads the file.

### Step 33. `Return test script` (No Operation)
On output `API`. The webhook answers with the binary field `testScript` of the **last node that ran**, which is this one.

> **Why not a "Respond to Webhook" node?** n8n refuses to start a workflow that has a Form Trigger *and* a Respond to Webhook node. Answering from the last node avoids that.

---

## Part H. Test, publish and export (Steps 34–37)

### Step 34. Preview run (no Jira)
Execute the workflow, upload the sample CR and both wireframes, choose **No**. Open the downloaded file and check:
- **Summary**: the title, the CR line, one row per section, and PENDING = TOTAL.
- A section sheet: set a few Results to PASS and FAIL. The Summary counts change immediately.
- **Traceability**: every criterion says *Yes*.

### Step 35. Jira run (mock)
Choose **Yes**, project `CPAY`, and type `CPAY-1, CPAY-2` in *Existing Jira stories*. Then open http://localhost:8089/_state:
- new stories `CPAY-3…` with labels `ai-generated-story` and `req2test-…`;
- one `QA: …` ticket per story, and a `Relates` link for each;
- `CPAY-1` and `CPAY-2` unchanged (read, not recreated).

### Step 36. Run it again: nothing is duplicated
Submit the same form again. The completion message should say **0 created** and **N already in Jira**, and the QA tickets get comments instead of copies.

### Step 37. Publish and export
**Publish** (top right), then use the form's Production URL. To keep the workflow in Git: ⋯ → **Download**, and save it as `workflows/01-requirements-to-test-script.json`. Check that the file contains no keys: credentials are stored as ids only.

---

## Concepts worth understanding

| Concept | Where you used it | Why it matters |
|---|---|---|
| **Structured outputs** | `output_config.format` in steps 9 and 19 | The API guarantees schema-valid JSON. No regex parsing, no retries for broken JSON. |
| **Effort** | `EFFORT` constants | How much Claude thinks before answering. High for the document, medium per story. |
| **Paired items** | `$('Plan stories').item` after HTTP nodes | Lets a node look up the input item that produced the current item, even across nodes. |
| **Merge in Append mode** | steps 18, 28 | Joins branches that may be empty. It runs as soon as one input has data. |
| **Decide, then act** | `Plan stories`, `Lay out test script` | Every Jira write is planned in code you can test, and Jira nodes stay simple. |
| **Idempotency** | change-request label, scope matching, `QA: ` prefix | Re-running is safe: nothing is created twice. |
| **Continue on error** | all Jira nodes | One bad ticket doesn't lose the test script. Errors appear in the Excel. |
| **Formulas, not numbers** | Summary sheet | The test script stays correct while testers work in it. |

## Common mistakes

| Symptom | Cause |
|---|---|
| `Cannot read properties of undefined (reading 'json')` in a Code node | A node was renamed. Code nodes use the exact names from this guide. |
| All files arrive as documents | The Wireframes field isn't named `Wireframes`, so the binary keys don't start with it |
| Test cases generated twice | Two branches feed one node *and* both ran. Use the If/Switch outputs exactly as shown: only one branch must reach `Look for earlier runs?` and `Plan stories`. |
| `Unexpected end of JSON input` on `Link QA ticket to story` | Response Format isn't **Text** |
| `No binary data with field testScript found` | `Build Excel test script` doesn't put its output in `testScript` |
| Form never finishes | A Code node threw an error. Open **Executions** to see which. The form shows only a generic message. |
| Jira `400` *issuetype* | `storyIssueType` / `qaIssueType` doesn't exist in that project. Check the project's issue types. |
