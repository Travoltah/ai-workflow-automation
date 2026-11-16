# AI Workflow Automation

A portfolio of production-minded AI workflows by **Trevor Kauyu**: Data Quality & AI Assurance Engineer.

Each project is a complete, runnable build: importable workflows, sample data, setup instructions, and an **evaluation suite**, because an AI workflow you can't measure is one you can't trust.

## Projects

| # | Project | What it does | Stack |
|---|---|---|---|
| 01 | [RAG FAQ Chatbot](projects/01-rag-faq-chatbot/) | Customer-support bot that answers only from FAQ documents, cites sources, refuses to guess, and logs knowledge gaps | n8n · Claude · Qdrant · OpenAI embeddings · Postgres |
| 02 | [Jira Test-Case Generator](projects/02-jira-test-case-generator/) | Turns Jira user stories into traceable manual test cases (boundary, negative, security), checks coverage, posts them back to Jira, and asks for clarification instead of guessing | n8n · Claude (structured outputs) · Jira Cloud · Postgres |
| 03 | [Requirements to Test Script](projects/03-requirements-to-test-script/) | Turns an FSD or Change Request (Word/PDF) and wireframes into Jira user stories with acceptance criteria, linked QA tickets, and a bank-style Excel test script, without recreating existing stories | n8n · Claude (structured outputs) · Jira Cloud REST · Python (python-docx, openpyxl) |

*More projects are added here as they're built.*

## Principles behind every project

1. **Grounded, not guessed.** Models answer from verified data, and say so when they can't.
2. **Data quality first.** Ingestion is idempotent, metadata is traceable, and duplicates are prevented by design.
3. **Measured.** Every project ships with test cases and a script that reports accuracy, refusals and latency, with quality gates.
4. **Secure by default.** No secrets in the repository, credentials stay in the workflow tool's encrypted store, and there are guardrails against prompt injection and sensitive-data collection.
5. **Reproducible.** Docker Compose stacks with pinned versions, so anyone can run the project locally.

## Repository layout

```
ai-workflow-automation/
├── projects/
│   └── NN-project-name/        # one self-contained folder per project
│       ├── README.md           # problem, architecture, setup, evaluation, cost
│       ├── workflows/          # exported workflow JSON (no credentials)
│       ├── evaluation/         # test cases + evaluation script
│       └── docker-compose.yml  # local stack, if the project needs one
├── templates/
│   └── PROJECT_README.md       # starting point for new projects
└── docs/
    └── CONVENTIONS.md          # naming, security and documentation rules
```

## Adding a new project

1. Copy `templates/PROJECT_README.md` into `projects/NN-short-name/README.md`.
2. Export workflows from n8n (**⋯ → Download**) into `workflows/`. Check that no credentials or personal data are inside.
3. Add test cases and an evaluation script.
4. Add a row to the **Projects** table above.

See [docs/CONVENTIONS.md](docs/CONVENTIONS.md) for the details.

## More work

- [QA Test Automation](https://github.com/Travoltah/qa-test-automation): Selenium, Postman and test planning
- [Data Science Projects](https://github.com/Travoltah/data-science-projects): machine learning, NLP and BI dashboards

## Contact

- Portfolio: [trevor-kauyu.vercel.app](https://trevor-kauyu.vercel.app)
- LinkedIn: [linkedin.com/in/trevor-kauyu](https://www.linkedin.com/in/trevor-kauyu/)

## License

[MIT](LICENSE): free to use and adapt, with attribution.
