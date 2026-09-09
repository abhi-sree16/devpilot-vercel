"""DevPilot for Vercel — FastAPI backend + static frontend (same dark UI).

Deploy: vercel.com → import repo → env vars pettu → done. (README chuddu)
Local:  uvicorn app:app --port 8502
"""
import os
import re
import time
from datetime import date, timedelta

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="DevPilot")

# ── Config / env ──────────────────────────────────────────────────────────
GH_API = "https://api.github.com"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
# Model fallback chain — high-demand (503) unte automatic ga next model
# (3.6-flash first: flash-latest sep-2026 lo stalls ayyindi — adaptive order kuda chuddu)
GEMINI_MODELS = [
    "gemini-3.6-flash",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
]
_last_good_model = None  # ye model last work aindo — adhi first try (adaptive)
LC_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) DevPilot/1.0",
}


def env(key, default=""):
    return os.environ.get(key, default)


# ── Auth (APP_PASSWORD) ───────────────────────────────────────────────────
class AuthError(Exception):
    pass


def check_auth(request: Request):
    pw = env("APP_PASSWORD")
    if not pw:
        raise AuthError("APP_PASSWORD env var set cheyali (Vercel → Settings → Environment Variables)")
    if request.headers.get("x-app-password", "") != pw:
        raise AuthError("Password wrong appudu! (app lo password check chey)")


# ── LLM (free Gemini, OpenAI-compatible) ─────────────────────────────────
def ask(prompt, max_tokens=6000):
    global _last_good_model
    key = env("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY env var ledu — Vercel settings lo pettu")
    deadline = time.time() + 50  # HARD deadline — Vercel 60s function limit
    last_err = "no model tried"
    models = [m for m in GEMINI_MODELS if m != _last_good_model]
    if _last_good_model:
        models.insert(0, _last_good_model)
    for model in models:
        remaining = deadline - time.time()
        if remaining < 8:  # inka attempt ki time ledu
            break
        try:
            r = requests.post(
                GEMINI_BASE + "/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=(min(10, remaining), min(40, remaining)))  # deadline lopala ne
        except requests.RequestException:
            last_err = f"{model}: network/timeout"
            continue  # inko model try chey — time waste cheyaku
        if r.status_code == 401:
            raise RuntimeError("LLM auth fail (401) — GEMINI_API_KEY check chey")
        if r.status_code == 200:
            try:
                content = (r.json()["choices"][0]["message"].get("content") or "").strip()
            except (KeyError, IndexError, ValueError):
                content = ""
            if content:
                _last_good_model = model  # idi work aindi — next time idi first
                return content
            last_err = f"{model}: empty response (thinking tokens)"
            continue
        # 429/503 — sleep cheyakunda direct ga next model
        last_err = f"{model} → HTTP {r.status_code}"
    raise RuntimeError(f"LLM API fail — {last_err}")


def ask_json(prompt, keys, max_tokens=6000):
    import json as _json
    raw = ask(prompt, max_tokens=max_tokens)
    try:
        data = _json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except (ValueError, _json.JSONDecodeError) as e:
        raise RuntimeError(f"LLM valid JSON ivvaledu ({e}) — malli try chey")
    miss = [k for k in keys if k not in data]
    if miss:
        raise RuntimeError(f"LLM JSON lo keys missing: {', '.join(miss)} — malli try chey")
    return data


# ── LeetCode (public GraphQL) ─────────────────────────────────────────────
def fetch_daily():
    r = requests.post(
        "https://leetcode.com/graphql",
        json={"query": """query { activeDailyCodingChallengeQuestion { date link
          question { questionFrontendId title titleSlug difficulty content } } }"""},
        headers=LC_HEADERS, timeout=20)
    r.raise_for_status()
    q = (r.json().get("data") or {}).get("activeDailyCodingChallengeQuestion")
    if not q or not q.get("question"):
        raise RuntimeError("LeetCode daily response empty — tarvata try chey")
    return q


def lc_recent_ac(username, limit=20):
    try:
        r = requests.post(
            "https://leetcode.com/graphql",
            json={"query": "query($u:String!){ recentAcSubmissionList(username:$u, "
                           "limit:%d){ title titleSlug timestamp } }" % limit,
                  "variables": {"u": username}},
            headers=LC_HEADERS, timeout=15)
        return ((r.json().get("data") or {}).get("recentAcSubmissionList")) or []
    except Exception:
        return []


def lc_stats(username):
    try:
        r = requests.post(
            "https://leetcode.com/graphql",
            json={"query": """query($u:String!){ matchedUser(username:$u){
                username profile{ ranking }
                submitStats{ acSubmissionNum{ difficulty count } } } }""",
                  "variables": {"u": username}},
            headers=LC_HEADERS, timeout=15)
        return (r.json().get("data") or {}).get("matchedUser")
    except Exception:
        return None


# ── GitHub (REST — PyGithub dependency vaddu) ─────────────────────────────
_owner = None


def gh_headers():
    return {"Authorization": f"Bearer {env('GITHUB_TOKEN')}",
            "Accept": "application/vnd.github+json"}


def gh_owner():
    global _owner
    if not _owner:
        r = requests.get(f"{GH_API}/user", headers=gh_headers(), timeout=20)
        r.raise_for_status()
        _owner = r.json()["login"]
    return _owner


def gh_repo_full(name):
    return f"{gh_owner()}/{name or env('GITHUB_REPO')}"


def upsert_file(repo, path, msg, content):
    url = f"{GH_API}/repos/{gh_repo_full(repo)}/contents/{path}"
    get = requests.get(url, headers=gh_headers(), timeout=20)
    body = {"message": msg, "content": _b64(content)}
    if get.status_code == 200:
        body["sha"] = get.json()["sha"]
    put = requests.put(url, headers=gh_headers(), json=body, timeout=30)
    if put.status_code not in (200, 201):
        raise RuntimeError(f"GitHub push fail ({path}): {put.json().get('message', put.status_code)}")
    return True


def read_file(repo, path):
    url = f"{GH_API}/repos/{gh_repo_full(repo)}/contents/{path}"
    r = requests.get(url, headers=gh_headers(), timeout=20)
    if r.status_code != 200:
        return None
    import base64
    return base64.b64decode(r.json()["content"]).decode("utf-8", errors="replace")


def _b64(text):
    import base64
    return base64.b64encode(text.encode()).decode()


# ── Routes ────────────────────────────────────────────────────────────────
@app.get("/")
def home():
    with open("index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/daily")
def api_daily(request: Request):
    try:
        check_auth(request)
    except AuthError as e:
        return {"ok": False, "error": str(e), "auth": False}
    try:
        q = fetch_daily()
        m = q["question"]
        already = False
        lcu = env("LEETCODE_USERNAME")
        if lcu:
            already = m["titleSlug"] in {s.get("titleSlug") for s in lc_recent_ac(lcu)}
        raw = m.get("content") or ""
        raw = re.sub(r"<br\s*/?>|</p>|</pre>|</li>|</ul>|</ol>|</h\d>", "\n", raw)
        raw = re.sub(r"<[^>]+>", " ", raw)
        import html as _html
        raw = _html.unescape(re.sub(r"[ \t]{2,}", " ", raw))
        return {"ok": True, "date": q["date"], "num": m["questionFrontendId"],
                "title": m["title"], "slug": m["titleSlug"],
                "difficulty": m["difficulty"], "content": raw.strip(),
                "link": q["link"], "already_solved": already}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/stats")
def api_stats(request: Request):
    try:
        check_auth(request)
    except AuthError as e:
        return {"ok": False, "error": str(e), "auth": False}
    try:
        solved = streak = posts = 0
        recent, lc = [], None
        repo, token = env("GITHUB_REPO"), env("GITHUB_TOKEN")
        if token and repo:
            log = read_file(repo, "LOG.md")
            if log:
                dates = set(re.findall(r"\| (\d{4}-\d{2}-\d{2}) \|", log))
                solved = len(dates)
                d = date.today()
                while d.isoformat() in dates:
                    streak += 1
                    d -= timedelta(days=1)
                recent = re.findall(r"\| (\d{4}-\d{2}-\d{2}) \| (\w+) \| \[([^\]]+)\]",
                                    log)[-5:][::-1]
            r = requests.get(f"{GH_API}/repos/{gh_repo_full(repo)}/contents/posts",
                             headers=gh_headers(), timeout=20)
            if r.status_code == 200 and isinstance(r.json(), list):
                posts = len(r.json())
        lcu = env("LEETCODE_USERNAME")
        if lcu:
            mu = lc_stats(lcu)
            if mu:
                lc = {"username": mu["username"],
                      "rank": (mu.get("profile") or {}).get("ranking"),
                      "stats": {d["difficulty"]: d["count"]
                                for d in mu["submitStats"]["acSubmissionNum"]}}
        return {"ok": True, "solved": solved, "streak": streak, "posts": posts,
                "recent": recent, "leetcode": lc, "repo": f"{gh_owner()}/{repo}",
                "today": date.today().isoformat()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/solve")
async def api_solve(request: Request):
    try:
        check_auth(request)
    except AuthError as e:
        return {"ok": False, "error": str(e), "auth": False}
    try:
        import json
        body = await request.json()
        kind = body.get("kind", "")

        if kind == "hints":
            p = body["problem"]
            text = ask(
                f"LeetCode {p['num']}. {p['title']} ({p['difficulty']})\n"
                f"{p.get('content', '')[:4000]}\n\n3 progressive hints ivvu — full solution vaddu.")
            return {"ok": True, "result": text}

        if kind == "solution":
            p = body["problem"]
            data = ask_json(f"""Solve this LeetCode problem.

{p['num']}. {p['title']} ({p['difficulty']})
{p.get('content', '')[:4000]}

JSON keys:
- approach: 2-3 sentences on the core idea, plain English
- complexity: "O(?) time, O(?) space"
- code: complete Python 3 class Solution, LeetCode-lo direct ga submit cheyochu
- linkedin_post: first-person post <120 words, hook + approach + lesson, max 2 emojis, 3-5 hashtags""",
                ["approach", "complexity", "code", "linkedin_post"])
            return {"ok": True, "result": data}

        if kind == "post":
            text = ask(f"""Write a LinkedIn post. {body['context']}
First person, <120 words, hook line first, one practical lesson, max 2 emojis,
3-5 hashtags tho end chey. "I am thrilled to share" lanti clichés vaddu.""")
            return {"ok": True, "result": text}

        if kind == "plan":
            # PHASE 1: meta + file list matrame (light → fast).
            # (Anni files content okate call lo 90s+ padutundi, Vercel 60s limit dhaati — so 2 phases)
            data = ask_json(f"""Design a portfolio project.
Idea: {body['idea']}
Level: {body.get('level', 'beginner')}

ALL OUTPUT IN ENGLISH — natural, like a real developer wrote it. No AI feel, no emoji spam.
JSON keys:
- name: short kebab-case GitHub repo name
- description: one line repo description (casual professional English)
- pitch: why this impresses recruiters, 3-4 lines, English
- files_list: array of 6-8 file paths — real complete project structure: README.md, correct extensions, folders (src/ etc.), core logic + styles + config anni cover chey
- first_tasks: 5 concrete next tasks, English""",
                ["name", "description", "pitch", "files_list", "first_tasks"])
            data["name"] = re.sub(r"[^a-zA-Z0-9-]", "-", str(data.get("name", "new-project"))).strip("-").lower() or "new-project"
            if not isinstance(data.get("files_list"), list) or not data["files_list"]:
                data["files_list"] = ["README.md", "index.html", "style.css", "app.js"]
            data["files_list"] = [re.sub(r"\.\.", "", str(p)).lstrip("/") for p in data["files_list"]][:9]
            return {"ok": True, "result": data}

        if kind == "plan_files":
            # PHASE 2: batch of 3 files content (frontend batches istundi — prathi call light)
            data = ask_json(f"""Project "{body.get('name', '')}" (idea: {body.get('idea', '')}, level: {body.get('level', 'beginner')}).
Project structure (already decided): {body.get('all_files', body['files_list'])}
Write COMPLETE contents for EXACTLY these files: {body["files_list"]}

STYLE — this goes to a public GitHub repo, must look 100% human-written:
- Everything in English
- Code like real developers write: minimal comments, only where genuinely needed
- NO AI-style writing: "Certainly", "This project leverages", "In this file we will", "Let's", excessive bullets, emoji spam
- README.md: short and practical — what it does, quick start steps. No badge walls, no hype.

JSON keys:
- files: JSON object path: content. Real working code — full logic, functions, imports. Each file under 60 lines.""",
                ["files"], max_tokens=4500)
            return {"ok": True, "result": data}
            data["name"] = re.sub(r"[^a-zA-Z0-9-]", "-", str(data.get("name", "new-project"))).strip("-").lower() or "new-project"
            return {"ok": True, "result": data}

        if kind == "progress":
            data = ask_json(
                f'Project "{body["repo"]}" — what I worked on: {body["did"]}\n'
                'summary and next MUST be in ENGLISH (they get pushed to the public repo PROGRESS.md). '
                'JSON keys: summary (3 bullets, English), next (3 next steps, English), '
                'linkedin_post (build-in-public post <100 words)',
                ["summary", "next", "linkedin_post"])
            return {"ok": True, "result": data}

        return {"ok": False, "error": f"unknown kind: {kind}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/github")
async def api_github(request: Request):
    try:
        check_auth(request)
    except AuthError as e:
        return {"ok": False, "error": str(e), "auth": False}
    try:
        body = await request.json()
        action = body.get("action", "")

        if action == "commit_solution":
            if not env("GITHUB_TOKEN") or not env("GITHUB_REPO"):
                raise RuntimeError("GITHUB_TOKEN / GITHUB_REPO env vars ledu")
            p, sol = body["problem"], body["solution"]
            repo, base = env("GITHUB_REPO"), f"{p['date']}-{p['slug']}"
            upsert_file(repo, f"{base}/solution.py", f"solve: {base}", sol["code"])
            upsert_file(repo, f"{base}/README.md", f"docs: {base}",
                        f"# {p['num']}. {p['title']}\n\n"
                        f"**Difficulty:** {p['difficulty']}  \nhttps://leetcode.com{p['link']}\n\n"
                        f"## Approach\n{sol['approach']}\n\n## Complexity\n{sol['complexity']}\n")
            log = read_file(repo, "LOG.md") or \
                "# Streak\n\n| Date | Difficulty | Problem |\n|------|------------|---------|\n"
            upsert_file(repo, "LOG.md", f"log: {p['date']}", log +
                        f"| {p['date']} | {p['difficulty']} | [{p['title']}](/{base}/) |\n")
            return {"ok": True, "url": f"https://github.com/{gh_repo_full(repo)}"}

        if action == "save_post":
            upsert_file(env("GITHUB_REPO"), f"posts/{date.today().isoformat()}-post.md",
                        "post draft", body["content"])
            return {"ok": True}

        if action == "create_main_repo":
            r = requests.post(f"{GH_API}/user/repos", headers=gh_headers(),
                              json={"name": env("GITHUB_REPO"),
                                    "description": "LeetCode daily solutions — DevPilot"},
                              timeout=30)
            if r.status_code not in (201, 422):
                raise RuntimeError(f"Repo create fail: {r.json().get('message', r.status_code)}")
            return {"ok": True, "url": f"https://github.com/{gh_repo_full(env('GITHUB_REPO'))}"}

        if action == "project_repo":
            plan = body["plan"]
            r = requests.post(f"{GH_API}/user/repos", headers=gh_headers(),
                              json={"name": plan["name"],
                                    "description": str(plan.get("description", ""))},
                              timeout=30)
            if r.status_code not in (201, 422):
                raise RuntimeError(f"Repo create fail: {r.json().get('message', r.status_code)} — "
                                   "token ki 'repo' scope kavali")
            for i, (path, content) in enumerate(plan["files"].items()):
                upsert_file(plan["name"], path,
                            "initial commit" if i == 0 else f"add {path}", content)
            upsert_file(plan["name"], "TODO.md", "update TODO.md",
                        "\n".join(f"- [ ] {t}" for t in plan.get("first_tasks", [])))
            return {"ok": True, "url": f"https://github.com/{gh_repo_full(plan['name'])}"}

        if action == "progress":
            repo = body["repo"]
            old = read_file(repo, "PROGRESS.md") or "# Progress\n"
            upsert_file(repo, "PROGRESS.md", "update PROGRESS.md",
                        old + f"\n## {date.today().isoformat()}\n"
                        + "\n".join(f"- {s}" for s in body["summary"]) + "\n")
            return {"ok": True, "url": f"https://github.com/{gh_repo_full(repo)}"}

        return {"ok": False, "error": f"unknown action: {action}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
