# Conventions

Rules that keep every project in this repository consistent, safe to publish, and easy to run.

## Naming
- Project folders: `NN-short-kebab-name` (e.g. `02-invoice-extraction`), numbered in the order they were built.
- Workflow files: `NN-what-it-does.json`, numbered in the order they should be imported or run.
- Workflow names inside n8n: `<Project> · N. <Purpose>` (e.g. `RAG FAQ · 2. FAQ chatbot`), so they group together in the n8n list.
- Node names describe the business step ("Log unanswered question"), not the node type ("Postgres1").

## Security checklist (before every commit)
- [ ] No API keys, tokens, passwords or `.env` files. Only `.env.example` with placeholders.
- [ ] Exported workflows contain no `credentials` blocks with real IDs or values. n8n exports never include secret values, but check anyway.
- [ ] No personal or customer data in sample datasets. Use clearly fictional companies (Contoso, Northwind…).
- [ ] Public endpoints (chat triggers, webhooks, forms) are documented as such, with production hardening notes.
- [ ] Docker images are pinned to a specific version.

## Documentation standard
Every project README answers, in this order:
1. **What and why**: the business problem in plain language.
2. **Architecture**: a Mermaid diagram of the data flow.
3. **Setup**: copy-paste steps from zero to a working demo.
4. **Evaluation**: how quality is measured, and how to run it.
5. **Configuration & cost**: what can be changed, and what it costs to run.
6. **Security & governance**: data handling, guardrails, known limits.
7. **Troubleshooting & roadmap.**

Only publish evaluation numbers that came from a real run, and include the date and the model version used.

## Evaluation standard
- At least 15 test cases, including **out-of-scope** questions the workflow must decline.
- Expected results are checkable facts (keywords, numbers, labels), not vibes.
- The script exits non-zero when a quality gate fails, so it can run in CI.
- Re-run it after any change to prompts, models, chunking or data, and record the results.

## Commit messages
[Conventional Commits](https://www.conventionalcommits.org/): `feat(rag-faq): add gap report view`, `fix(rag-faq): handle empty uploads`, `docs: update project table`.
