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
def _strip_html(raw):
    raw = re.sub(r"<br\s*/?>|</p>|</pre>|</li>|</ul>|</ol>|</h\d>", "\n", raw or "")
    raw = re.sub(r"<[^>]+>", " ", raw)
    import html as _html
    return _html.unescape(re.sub(r"[ \t]{2,}", " ", raw)).strip()


def fetch_daily():
    r = requests.post(
        "https://leetcode.com/graphql",
        json={"query": """query { activeDailyCodingChallengeQuestion { date link
          question { questionFrontendId title titleSlug difficulty content } } }"""},
        headers=LC_HEADERS, timeout=15)
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
            headers=LC_HEADERS, timeout=10)
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
            headers=LC_HEADERS, timeout=10)
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
        r = requests.get(f"{GH_API}/user", headers=gh_headers(), timeout=12)
        r.raise_for_status()
        _owner = r.json()["login"]
    return _owner


def gh_repo_full(name):
    return f"{gh_owner()}/{name or env('GITHUB_REPO')}"


def upsert_file(repo, path, msg, content):
    url = f"{GH_API}/repos/{gh_repo_full(repo)}/contents/{path}"
    get = requests.get(url, headers=gh_headers(), timeout=12)
    body = {"message": msg, "content": _b64(content)}
    if get.status_code == 200:
        body["sha"] = get.json()["sha"]
    put = requests.put(url, headers=gh_headers(), json=body, timeout=30)
    if put.status_code not in (200, 201):
        raise RuntimeError(f"GitHub push fail ({path}): {put.json().get('message', put.status_code)}")
    return True


def read_file(repo, path):
    url = f"{GH_API}/repos/{gh_repo_full(repo)}/contents/{path}"
    r = requests.get(url, headers=gh_headers(), timeout=12)
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
        return {"ok": True, "date": q["date"], "num": m["questionFrontendId"],
                "title": m["title"], "slug": m["titleSlug"],
                "difficulty": m["difficulty"], "content": _strip_html(m.get("content")),
                "link": q["link"], "already_solved": already}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/lc_search")
def api_lc_search(request: Request, q: str = ""):
    """LeetCode full library search — daily kakunda ANY problem."""
    try:
        check_auth(request)
    except AuthError as e:
        return {"ok": False, "error": str(e), "auth": False}
    try:
        r = requests.post(
            "https://leetcode.com/graphql",
            json={
                "query": """query problemsetQuestionList($categorySlug:String,$limit:Int,
                  $skip:Int,$filters:QuestionListFilterInput){
                  problemsetQuestionList:questionList(categorySlug:$categorySlug,
                  limit:$limit,skip:$skip,filters:$filters){
                  questions:data{questionFrontendId title titleSlug difficulty} } }""",
                "variables": {"categorySlug": "", "skip": 0, "limit": 12,
                              "filters": {"searchKeywords": q or "a"}}},
            headers=LC_HEADERS, timeout=15)
        r.raise_for_status()
        qs = (((r.json().get("data") or {}).get("problemsetQuestionList") or {})
              .get("questions")) or []
        return {"ok": True, "results": [
            {"num": x.get("questionFrontendId"), "title": x.get("title"),
             "slug": x.get("titleSlug"), "difficulty": x.get("difficulty")}
            for x in qs if x.get("titleSlug")]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/lc_problem")
def api_lc_problem(request: Request, slug: str = ""):
    """Full problem content by slug (search nunchi click chesinappudu)."""
    try:
        check_auth(request)
    except AuthError as e:
        return {"ok": False, "error": str(e), "auth": False}
    try:
        if not slug:
            return {"ok": False, "error": "slug kavali"}
        r = requests.post(
            "https://leetcode.com/graphql",
            json={"query": """query questionDetail($titleSlug:String!){
              question(titleSlug:$titleSlug){
              questionFrontendId title titleSlug difficulty content } }""",
                  "variables": {"titleSlug": slug}},
            headers=LC_HEADERS, timeout=15)
        r.raise_for_status()
        m = (r.json().get("data") or {}).get("question")
        if not m:
            return {"ok": False, "error": "Problem dhorakaledu — slug check chey"}
        already = False
        lcu = env("LEETCODE_USERNAME")
        if lcu:
            already = m["titleSlug"] in {s.get("titleSlug") for s in lc_recent_ac(lcu)}
        return {"ok": True, "date": date.today().isoformat(),
                "num": m["questionFrontendId"], "title": m["title"],
                "slug": m["titleSlug"], "difficulty": m["difficulty"],
                "content": _strip_html(m.get("content")),
                "link": f"/problems/{slug}/", "already_solved": already}
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
                             headers=gh_headers(), timeout=12)
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
            head = (f"{p['num']}. " if str(p.get("num") or "").strip() else "") + p["title"]
            text = ask(
                f"{head} ({p['difficulty']})\n"
                f"{p.get('content', '')[:4000]}\n\n3 progressive hints ivvu — full solution vaddu.")
            return {"ok": True, "result": text}

        if kind == "solution":
            p = body["problem"]
            head = (f"{p['num']}. " if str(p.get("num") or "").strip() else "") + p["title"]
            data = ask_json(f"""Solve this coding problem.

{head} ({p['difficulty']})
{p.get('content', '')[:4000]}

JSON keys:
- approach: 2-3 sentences on the core idea, plain English
- complexity: "O(?) time, O(?) space"
- code: complete Python 3 solution (LeetCode problem ante "class Solution" format, leda clean function format)
- linkedin_post: first-person post <120 words, hook + approach + lesson, max 2 emojis, 3-5 hashtags""",
                ["approach", "complexity", "code", "linkedin_post"])
            return {"ok": True, "result": data}

        if kind == "post":
            text = ask(f"""Write a LinkedIn post. {body['context']}
First person, <120 words, hook line first, one practical lesson, max 2 emojis,
3-5 hashtags tho end chey. "I am thrilled to share" lanti clichés vaddu.""")
            return {"ok": True, "result": text}

        if kind == "speak":
            mode, phase = body.get("mode", "interview"), body.get("phase", "")
            hist = body.get("history") or []
            htxt = "\n".join(
                (h.get("name") or ("You" if h.get("who") == "me" else "AI")) + ": " + h.get("text", "")
                for h in hist[-16:])

            if phase == "start":
                if mode == "interview":
                    data = ask_json(
                        f'You are a friendly professional interviewer for a "{body.get("role") or "software engineer"}" position. Mock interview practice.\n'
                        'Start: warm 1-line greeting + FIRST question (opener like "tell me about yourself" or a role-based one). ONE question only, 2-3 sentences total.\n'
                        'English lo matladu. JSON keys: reply (string)', ["reply"])
                    return {"ok": True, "result": data}
                if mode == "gd":
                    topic = body.get("topic") or "Is AI a bigger threat or an opportunity for jobs?"
                    data = ask_json(
                        f'Group Discussion practice. Topic: "{topic}".\n'
                        'You play 2 participants: Priya (supports the topic) and Arjun (skeptical/critical view).\n'
                        'Start the GD: Priya opens with a strong point (2-3 sentences).\n'
                        'English, natural GD tone. JSON keys: replies (array of {name, text})', ["replies"])
                    return {"ok": True, "result": data}
                if mode == "jam":
                    topic = body.get("topic") or ""
                    if not topic:
                        topic = ask("Give one interesting Just-A-Minute (JAM) speaking topic — tech, careers, or daily life. Topic line matrame, English.", max_tokens=300).strip().strip('"')
                    return {"ok": True, "result": {"topic": topic,
                            "reply": "Your JAM topic: " + topic + "\n\nSpeak for 60 seconds — structure: opening line, 2-3 points, short conclusion. Mic press chesi matladam start chey!"}}
                return {"ok": False, "error": f"unknown mode: {mode}"}

            if phase == "reply":
                user_reply = body.get("user_reply", "")
                if mode == "interview":
                    data = ask_json(
                        f'Mock interview for "{body.get("role") or "software engineer"}" position. Transcript:\n{htxt}\n\nCandidate: "{user_reply}"\n'
                        'Respond as the interviewer: brief acknowledgment + the NEXT question (dig into projects/skills from their answer; mix technical + behavioral). ONE question, 2-3 sentences.\n'
                        'JSON keys: reply', ["reply"])
                elif mode == "gd":
                    data = ask_json(
                        f'GD topic: "{body.get("topic") or ""}". Transcript:\n{htxt}\n\nCandidate: "{user_reply}"\n'
                        'Participants Priya (pro) and Arjun (skeptic) respond to the candidate point. Pick ONE participant (or both, briefly). Natural GD tone — agree/disagree with substance, 2-3 sentences each.\n'
                        'JSON keys: replies (array of {name, text})', ["replies"])
                else:  # jam → user speech complete, direct feedback
                    data = ask_json(
                        f'JAM (1-minute speech) on "{body.get("topic")}". Transcript:\n{htxt}\n\nSpeech:\n"{user_reply}"\n'
                        'Evaluate the speech. JSON keys: score (1-10), strengths (3 bullets), improvements (3), tips (3) — English, honest.',
                        ["score", "strengths", "improvements", "tips"])
                    return {"ok": True, "result": data, "done": True}
                return {"ok": True, "result": data}

            if phase == "feedback":
                data = ask_json(
                    f"Mock {mode} session transcript:\n{htxt}\n\n"
                    "Give honest communication feedback. JSON keys:\n"
                    "- score: 1-10 number\n- strengths: 3 bullets (English)\n- improvements: 3 bullets\n- tips: 3 practical tips",
                    ["score", "strengths", "improvements", "tips"])
                return {"ok": True, "result": data}

            return {"ok": False, "error": f"unknown phase: {phase}"}

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
            plat = str(p.get("platform") or "").strip()
            head = (f"{p['num']}. " if str(p.get("num") or "").strip() else "") + p["title"]
            disp = (f"[{plat}] " if plat else "") + head
            link = str(p.get("link") or "")
            if link and not link.startswith("http"):
                link = "https://leetcode.com" + link
            upsert_file(repo, f"{base}/solution.py", f"solve: {base}", sol["code"])
            upsert_file(repo, f"{base}/README.md", f"docs: {base}",
                        f"# {disp}\n\n"
                        f"**Difficulty:** {p['difficulty']}  \n"
                        + (f"**Platform:** {plat}  \n" if plat else "")
                        + (f"{link}\n" if link else "\n")
                        + f"\n## Approach\n{sol['approach']}\n\n## Complexity\n{sol['complexity']}\n")
            log = read_file(repo, "LOG.md") or \
                "# Streak\n\n| Date | Difficulty | Problem |\n|------|------------|---------|\n"
            upsert_file(repo, "LOG.md", f"log: {p['date']}", log +
                        f"| {p['date']} | {p['difficulty']} | [{disp}](/{base}/) |\n")
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

        return {"ok": False, "error": f"unknown action: {action}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
