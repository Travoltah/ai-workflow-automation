# Build guide: LinkedIn Content Studio

Two parts work together: the **website** (Next.js on Vercel: the admin pages, the API, the style check, the image renderer and the database) and **n8n** (on your machine: Claude and LinkedIn calls). You can test everything against the **mock LinkedIn API** before connecting a real account.

## 1. Website

The Content Studio is part of the portfolio website. On a fresh copy:

1. **Database.** Apply the migrations (they add `StudioSettings`, `StudioTopic`, `StudioItem` and `StudioComment`):
   ```bash
   npx prisma migrate deploy        # production: run it with the production DATABASE_URL
   npx prisma migrate dev           # local development
   ```
2. **Token.** n8n authenticates with a shared secret. Generate one (at least 24 characters) and add it as `STUDIO_API_TOKEN` to `.env` locally and to the Vercel project's environment variables:
   ```bash
   node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"
   ```
3. **Images.** Approved covers and infographics are stored in Vercel Blob (`BLOB_READ_WRITE_TOKEN`, public store) on Vercel, and in `public/uploads/studio` locally. The image fonts (Inter, SIL Open Font License) are bundled in `src/lib/studio/fonts`.
4. **Settings.** In `/admin/studio/settings`: your **voice notes** (stories you're happy to mention, words you never use, topics to avoid), the **name and titles** printed on images, the schedule and the topic queue.

Check: `curl -H "Authorization: Bearer $STUDIO_API_TOKEN" https://<your-site>/api/studio/jobs` returns JSON; without the header it returns 401.

## 2. n8n

```bash
cp .env.example .env          # fill in the passwords and N8N_ENCRYPTION_KEY
docker compose --profile test up -d --build      # n8n + its database + the mock LinkedIn API
```

Open n8n (http://localhost:5678), import `workflows/01-linkedin-content-studio.json`, and create three credentials:

| Credential | Type | Value |
|---|---|---|
| Website token | **Header Auth** | Name `Authorization`, value `Bearer <STUDIO_API_TOKEN>`. Select it on every node that calls `/api/studio` |
| Anthropic | **Anthropic** | your API key. Select it on the four "… with Claude" nodes |
| LinkedIn | **LinkedIn OAuth2 API** | see step 4. Until then, for the mock: a second **Header Auth** credential with `Authorization: Bearer mock-token`, and switch the LinkedIn nodes to it |

In the **Settings** node:

| Setting | Mock testing | Real use |
|---|---|---|
| `siteUrl` | `http://host.docker.internal:3000` (website on `npm run dev`) | `https://<your-site>` |
| `linkedinApi` | `http://mock-linkedin:8000` | `https://api.linkedin.com` |
| `linkedinVersion` | any `YYYYMM` | a current version month from LinkedIn's [versioning page](https://learn.microsoft.com/en-us/linkedin/marketing/versioning) |
| `readComments` | `true` | `false` unless your app has `r_member_social` |
| `model` | `claude-opus-5-5` | `claude-opus-5-5` |

Activate the workflow. It checks in every 30 minutes from 07:00 to 22:30 (edit the cron in **Every 30 minutes**). To start a run now: `curl -X POST http://localhost:5678/webhook/studio/run`.

> **Database wake-ups.** Each check-in queries the website's database. On Neon's free plan the database sleeps after 5 idle minutes; a 30-minute interval keeps it mostly asleep. Checking every 5 minutes would keep it awake all day.

## 3. Test against the mock

```bash
# offline: the Code nodes against real Claude responses (no API calls)
node evaluation/test-guardrails.js

# live: about $0.25 of Claude calls. You approve in between, as in real use.
export STUDIO_API_TOKEN=...            # same as the website's
python evaluation/evaluate.py draft      # then approve both drafts in /admin/studio
python evaluation/evaluate.py publish    # then approve the genuine replies in /admin/studio/comments
python evaluation/evaluate.py replies
```

The mock's request log and state are at http://localhost:8010/_log and /_state. Website unit tests for the style rules, the schedule and LinkedIn links: `npx vitest run tests/studio-*.test.ts` in the website repository.

## 4. Connect your LinkedIn account

1. At [linkedin.com/developers](https://www.linkedin.com/developers/apps), **create an app**. LinkedIn requires a Company Page to associate it with; any page you administer works.
2. Under **Products**, add **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**. Both are self-serve.
3. Under **Auth**, add n8n's OAuth redirect URL (shown when you create the credential, e.g. `http://localhost:5678/rest/oauth2-credential/callback`).
4. In n8n, create a **LinkedIn OAuth2 API** credential with the app's Client ID and Client Secret (Organization Support off), sign in, and select it on the LinkedIn nodes: Who am I, Start image upload, Upload cover, Create post, Post reply, Like comment, Read comments.
5. Set `linkedinApi` to `https://api.linkedin.com` and a current `linkedinVersion`. Keep `readComments` off.
6. Do a first real post with something low-stakes, and check it on LinkedIn.

**Comments without `r_member_social`.** On LinkedIn, open a comment's ··· menu, **Copy link to comment**, and paste it with the comment text in `/admin/studio/comments`. n8n drafts the reply; after you approve it, n8n posts it in the right thread and likes the comment.

## 5. Day to day

- **Generate now:** `/admin/studio` → topic and a short description → the draft appears at the next check-in.
- **Review:** read the article and post, look at the images, fix anything the style check flags (it runs as you type), then **Approve**. Approving an article publishes it on the website straight away; the LinkedIn post follows at the next check-in.
- **Regenerate with feedback** if the angle is wrong ("shorter, lead with the fraud-model example").
- **Replies:** approve, edit or skip each one in `/admin/studio/comments`.
- **Costs:** about $0.13 per article, $0.05 per post and under $0.01 per reply. Each item shows its cost.

## Troubleshooting

| Symptom | Cause |
|---|---|
| "Hasn't checked in yet" in the admin | n8n can't reach `siteUrl`, or the website token doesn't match `STUDIO_API_TOKEN` (the check-in returns 401) |
| A draft stays "Generating" | the run failed: open the execution in n8n. The website hands the draft out again after 30 minutes, up to 3 times |
| "LinkedIn didn't create the post: … unescaped reserved character" | the text reached LinkedIn without little-text escaping: check **Build post** wasn't edited |
| 426 from LinkedIn | `linkedinVersion` is too old. Use a current month |
| 403 on reply or like | the app lacks `w_member_social`, or the token expired: reconnect the credential |
