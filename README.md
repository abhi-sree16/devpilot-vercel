# ✈️ DevPilot — Vercel Edition

Daily LeetCode → GitHub → LinkedIn, on autopilot.

FastAPI backend (`app.py`) + single-file dark frontend (`index.html`).
Free **Vercel Hobby** plan meedha run avtundi. PyGithub vaddu — pure REST + requests.

## Modules

| Page | Em chesindi |
|------|-------------|
| **Dashboard** | streak, repo solutions, LeetCode profile (rank + Easy/Medium/Hard), recent commits |
| **LeetCode** | today's daily problem, AI hints, full solution (approach + code + complexity), LinkedIn post, **1-click GitHub commit** (`{date}-{slug}/solution.py` + `README.md` + `LOG.md` row) |
| **Projects** | idea → AI project plan → repo create + files push + TODO.md; progress updates → PROGRESS.md |
| **Posts** | LinkedIn drafts → AI generate/edit → save to `posts/{date}-post.md` |

## Deploy (5 minutes)

1. [vercel.com](https://vercel.com) → login (GitHub tho)
2. **Add New → Project** → GitHub account select chey → `devpilot-vercel` repo **Import**
3. Defaults vaipu proceed → **Deploy** (framework auto-detect — em change cheyalsina avasaram ledu)
4. **Settings → Environment Variables** lo 5 vars add chey:

   | Name | Value |
   |------|-------|
   | `GEMINI_API_KEY` | (AI Studio key) |
   | `GITHUB_TOKEN` | (classic PAT, `repo` scope) |
   | `GITHUB_REPO` | `leetcode-daily` |
   | `LEETCODE_USERNAME` | (LeetCode username) |
   | `APP_PASSWORD` | app open cheyadaniki password (nive decide chey) |

5. **Deployments → ⋯ → Redeploy** (env vars fresh ga load avvali)
6. URL open chey → APP_PASSWORD enter chey → done 🎉

> Password marchali antey: Vercel → Settings → Environment Variables → `APP_PASSWORD` update → Redeploy.

## Local run

```bash
pip install -r requirements.txt
APP_PASSWORD=test GEMINI_API_KEY=... GITHUB_TOKEN=... GITHUB_REPO=leetcode-daily \
LEETCODE_USERNAME=... uvicorn app:app --port 8502
# http://localhost:8502
```

## Auth

Deployed URL public kabatti **prathi `/api/*` request** `x-app-password` header check chestundi (frontend automatic ga pamputundi). Password browser localStorage lo untundi (Lock button tho clear cheyochu).

## Notes

- LLM: free Gemini (OpenAI-compatible endpoint) — 3-model fallback chain (503/429 kabati)
- LeetCode: public GraphQL API
- GitHub: REST contents API (upsert with SHA)
- Repo lo **secrets levu** — anni Vercel env vars lo untayi
