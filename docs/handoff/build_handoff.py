"""Builds docs/handoff/Tollgate-Handoff.pdf from this file (HTML + inline SVG diagrams).

    python3 docs/handoff/build_handoff.py            # writes handoff.html and the PDF (needs Google Chrome)

The diagrams are drawn here as SVG so the document stays editable and versioned with the code.
"""

import html
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
INDIGO, INK, MUTED, LINE = "#5e6ad2", "#1b1d22", "#6b6f7a", "#d9dbe1"
FILLS = {
    "default": ("#ffffff", LINE),
    "accent": ("#eef0fd", "#aeb4ef"),
    "store": ("#f6f7f9", LINE),
    "warn": ("#fff5e6", "#f0c37a"),
    "good": ("#eaf7ef", "#8fd1a8"),
    "bad": ("#fdecec", "#eba3a3"),
}

# --- tiny SVG toolkit --------------------------------------------------------------------------


def box(x: float, y: float, w: float, h: float, title: str, sub: str = "", kind: str = "default") -> str:
    fill, stroke = FILLS[kind]
    lines = [l for l in sub.split("\n") if l]
    text_y = y + h / 2 - (len(lines) * 7) + (4 if lines else 5)
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{fill}" stroke="{stroke}" stroke-width="1.3"/>',
        f'<text x="{x + w / 2}" y="{text_y}" text-anchor="middle" font-size="13" font-weight="600" fill="{INK}">{html.escape(title)}</text>',
    ]
    for i, line in enumerate(lines):
        parts.append(
            f'<text x="{x + w / 2}" y="{text_y + 16 + i * 14}" text-anchor="middle" font-size="10.5" fill="{MUTED}">{html.escape(line)}</text>'
        )
    return "".join(parts)


def arrow(x1: float, y1: float, x2: float, y2: float, label: str = "", dashed: bool = False, lx: float = 0, ly: float = 0) -> str:
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{MUTED}" stroke-width="1.4"{dash} marker-end="url(#arrow)"/>'
    if label:
        mx, my = (x1 + x2) / 2 + lx, (y1 + y2) / 2 + ly
        out += (
            f'<text x="{mx}" y="{my}" text-anchor="middle" font-size="10.5" fill="{INDIGO}" font-weight="600" '
            f'paint-order="stroke" stroke="#fcfcfd" stroke-width="5" stroke-linejoin="round">{html.escape(label)}</text>'
        )
    return out


def note(x: float, y: float, text: str, anchor: str = "start", color: str = MUTED, size: float = 10.5) -> str:
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" fill="{color}">{html.escape(text)}</text>'


def svg(width: int, height: int, *parts: str) -> str:
    defs = (
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{MUTED}"/></marker></defs>'
    )
    body = "".join(parts)
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="Inter, -apple-system, Segoe UI, Helvetica, Arial, sans-serif">{defs}{body}</svg>'
    )


# --- diagrams ----------------------------------------------------------------------------------


def d_architecture() -> str:
    return svg(
        900, 430,
        box(20, 40, 180, 64, "Your apps", "OpenAI SDK, n8n,\nOpen WebUI, scripts"),
        box(20, 250, 180, 64, "Browser", "people using\nthe dashboard"),
        box(260, 250, 190, 64, "Dashboard", "Next.js, port 3000", "accent"),
        box(260, 360, 190, 50, "Clerk (optional)", "sign-in for teams", "store"),
        box(500, 120, 200, 100, "Tollgate gateway", "FastAPI, port 8000\nkeys, limits, cache,\ncoalescing, fair queue", "accent"),
        box(750, 40, 135, 56, "Gemini API", "default models"),
        box(750, 130, 135, 56, "Ollama", "local models\n(optional)"),
        box(750, 220, 135, 50, "Mock upstream", "always fails (demo)", "store"),
        box(500, 290, 95, 64, "Redis: state", "keys, limits\nnever evicts", "store"),
        box(605, 290, 95, 64, "Redis: cache", "answers\nLFU, capped", "store"),
        box(553, 368, 100, 50, "Postgres", "keys, logs", "store"),
        arrow(200, 72, 497, 150, "/v1 + tg_live_ key", ly=-8),
        arrow(200, 282, 257, 282),
        arrow(355, 314, 355, 357),
        arrow(450, 270, 497, 200, "/admin + admin token", lx=-10, ly=18),
        arrow(700, 145, 747, 70),
        arrow(700, 165, 747, 158, dashed=True),
        arrow(700, 190, 747, 240, dashed=True),
        arrow(560, 220, 548, 287),
        arrow(640, 220, 652, 287),
        arrow(600, 220, 603, 365),
    )


def d_pipeline() -> str:
    y = 30
    steps = [
        ("Request arrives", "with a tg_live_ key", "default"),
        ("1. Auth", "key looked up in Redis (DB on a miss)", "default"),
        ("2. Limits", "requests per minute + daily tokens", "default"),
        ("3. Cache lookup", "answered before? reply in ms", "accent"),
        ("4. Coalescing", "same request in flight? share it", "accent"),
        ("5. Fair queue", "wait for a model slot, fairest first", "accent"),
        ("6. Model call", "with fallback to the next model", "default"),
        ("7. After the response", "bill tokens, maybe cache, log", "default"),
    ]
    parts = []
    for i, (t, s, k) in enumerate(steps):
        parts.append(box(250, y + i * 62, 300, 46, t, s, k))
        if i:
            parts.append(arrow(400, y + i * 62 - 16, 400, y + i * 62 - 1))
    parts += [
        box(620, y + 3 * 62, 230, 46, "Cache hit", "replay stored answer\n(JSON or stream)", "good"),
        arrow(550, y + 3 * 62 + 23, 617, y + 3 * 62 + 23, "yes", ly=-6),
        box(620, y + 4 * 62, 230, 46, "Follower", "receives the leader's\nstream as it arrives", "good"),
        arrow(550, y + 4 * 62 + 23, 617, y + 4 * 62 + 23, "yes", ly=-6),
        box(20, y + 1 * 62, 190, 46, "401", "unknown or revoked key", "bad"),
        arrow(250, y + 1 * 62 + 23, 213, y + 1 * 62 + 23),
        box(20, y + 2 * 62, 190, 46, "429", "over a limit (Retry-After)", "bad"),
        arrow(250, y + 2 * 62 + 23, 213, y + 2 * 62 + 23),
        box(20, y + 5 * 62, 190, 46, "429", "queue full / waited too long", "bad"),
        arrow(250, y + 5 * 62 + 23, 213, y + 5 * 62 + 23),
    ]
    return svg(870, 540, *parts)


def d_cache_admission() -> str:
    parts = [note(20, 22, "The same question asked three times (temperature 0):", color=INK, size=12)]
    rows = [
        ("1st time", "Not in cache. The model answers.", "Only a tiny 'seen' marker is kept (~100 bytes).", "warn", "admission_rejected"),
        ("2nd time", "Not in cache. The model answers.", "Seen before, so the answer is stored.", "accent", "miss (stored)"),
        ("3rd time", "Found in cache.", "Answered in milliseconds; the model is not used.", "good", "hit"),
    ]
    for i, (when, a, b, kind, header) in enumerate(rows):
        y = 40 + i * 80
        parts += [
            box(20, y, 110, 56, when, "", "store"),
            arrow(130, y + 28, 167, y + 28),
            box(170, y, 330, 56, a, b, kind),
            arrow(500, y + 28, 537, y + 28),
            box(540, y, 200, 56, "x-tollgate-cache", header),
        ]
    parts.append(note(20, 300, "One-off prompts (most prompts) never get past step 1, so they never push useful answers out.", size=11))
    return svg(760, 315, *parts)


def d_coalescing() -> str:
    parts = []
    for i, label in enumerate(["Client A (first)", "Client B", "Client C"]):
        y = 30 + i * 80
        kind = "accent" if i == 0 else "default"
        parts.append(box(20, y, 170, 50, label, "leader" if i == 0 else "follower (joins later)", kind))
        parts.append(arrow(190, y + 25, 327, 135 + (i - 1) * 12))
    parts += [
        box(330, 100, 200, 80, "One flight", "identical requests share it\nchunks are buffered", "accent"),
        arrow(530, 140, 627, 140, "1 model call", ly=-8),
        box(630, 110, 150, 60, "Model", "answers once"),
        note(330, 230, "Every client gets the full answer streamed live,", size=11),
        note(330, 246, "even ones that joined late. If client A disconnects,", size=11),
        note(330, 262, "B and C keep receiving. The model call is cancelled", size=11),
        note(330, 278, "only when nobody is listening any more.", size=11),
    ]
    return svg(800, 290, *parts)


def d_fair_queue() -> str:
    parts = [
        note(20, 20, "One model slot is free. Who goes next?", color=INK, size=12),
        box(20, 40, 230, 70, "Key A (busy script)", "counter: 12,000 tokens served\n18 requests waiting", "warn"),
        box(20, 130, 230, 70, "Key B (a person)", "counter: 300 tokens served\n1 request waiting", "good"),
        box(330, 80, 210, 80, "Fair queue (VTC)", "pick the waiting key with\nthe LOWEST counter", "accent"),
        arrow(250, 75, 327, 110),
        arrow(250, 165, 327, 132),
        arrow(540, 120, 617, 120, "Key B goes first", ly=-8),
        box(620, 90, 150, 60, "Model slot", "UPSTREAM_MAX_PARALLEL"),
        note(20, 235, "Counter = input tokens + 2 x output tokens, added while the answer streams.", size=11),
        note(20, 252, "A key that was idle starts at the lowest active counter, so it can't save up time.", size=11),
        note(20, 269, "Limits: 20 waiting requests per key and 30 s of waiting, then a clear 429.", size=11),
    ]
    return svg(790, 285, *parts)


def d_breaker() -> str:
    return svg(
        780, 230,
        box(30, 80, 170, 64, "Closed", "requests flow normally", "good"),
        box(310, 80, 170, 64, "Open", "model skipped for 30 s", "bad"),
        box(590, 80, 170, 64, "Half-open", "one trial request", "warn"),
        arrow(200, 100, 307, 100, "3 failures in a row", ly=-10),
        arrow(480, 100, 587, 100, "30 s later", ly=-10),
        arrow(675, 144, 675, 190),
        arrow(675, 190, 115, 190),
        arrow(115, 190, 115, 147),
        note(395, 205, "trial succeeds", anchor="middle", color=INDIGO),
        arrow(590, 125, 483, 125, "trial fails", ly=16),
    )


def d_logging() -> str:
    return svg(
        800, 200,
        box(20, 60, 170, 64, "Each request", "finishes and is logged", "default"),
        arrow(190, 92, 247, 92, "append (no I/O)", ly=-8),
        box(250, 60, 180, 64, "In-memory buffer", "fast, capped size", "accent"),
        arrow(430, 92, 497, 92, "every 2 s", ly=-8),
        box(500, 60, 130, 64, "Postgres", "request_logs", "store"),
        arrow(630, 92, 667, 92),
        box(670, 60, 110, 64, "Dashboard", "stats, charts,\nlogs"),
        note(20, 160, "The request path never waits for the database. If a write fails, the batch is retried next cycle.", size=11),
    )


def d_trust() -> str:
    return svg(
        820, 260,
        box(20, 30, 170, 60, "Browser", "signed in with Clerk\n(or localhost only)"),
        box(270, 30, 220, 60, "Dashboard server", "reads the user from Clerk", "accent"),
        box(570, 30, 230, 60, "Gateway /admin", "checks ADMIN_TOKEN, then\nscopes data to the user", "accent"),
        arrow(190, 60, 267, 60),
        arrow(490, 60, 567, 60, "ADMIN_TOKEN + X-Tollgate-User", ly=-10),
        box(20, 160, 170, 60, "Apps / SDKs", "send tg_live_ keys"),
        box(570, 160, 230, 60, "Gateway /v1", "key checked on every request", "accent"),
        arrow(190, 190, 567, 190, "Authorization: Bearer tg_live_...", ly=-8),
        note(270, 125, "ADMIN_TOKEN never reaches a browser.", size=11),
        note(270, 141, "Users only ever see their own keys, logs and usage.", size=11),
    )


def d_startup() -> str:
    return svg(
        840, 250,
        box(20, 20, 160, 56, "secrets-init", "creates admin token\n(first start only)", "store"),
        box(20, 100, 160, 50, "redis", "state, persistent", "store"),
        box(20, 160, 160, 50, "redis-cache", "answers, LFU", "store"),
        box(220, 60, 160, 50, "postgres", "bundled database", "store"),
        box(220, 160, 160, 56, "ollama + ollama-init", "only with\n--profile ollama", "warn"),
        box(450, 100, 170, 64, "backend", "gateway, port 8000\nmigrations on start", "accent"),
        box(670, 100, 150, 64, "frontend", "dashboard, port 3000", "accent"),
        arrow(180, 48, 447, 115),
        arrow(180, 125, 447, 128),
        arrow(180, 185, 447, 140),
        arrow(380, 85, 447, 120),
        arrow(380, 188, 447, 152, dashed=True),
        arrow(620, 132, 667, 132, "healthy", ly=-8),
        note(20, 240, "docker compose waits for each dependency to be healthy before starting the next service.", size=11),
    )


# --- document ------------------------------------------------------------------------------------


def fig(diagram: str, caption: str) -> str:
    return f'<figure>{diagram}<figcaption>{html.escape(caption)}</figcaption></figure>'


def img(name: str, caption: str) -> str:
    return f'<figure class="shot"><img src="img/{name}" alt="{html.escape(caption)}"/><figcaption>{html.escape(caption)}</figcaption></figure>'


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


CSS = f"""
@page {{ size: A4; margin: 18mm 16mm 18mm 16mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; color: {INK}; font-size: 10.5pt; line-height: 1.55; }}
h1 {{ font-size: 26pt; letter-spacing: -0.02em; margin: 0 0 6px; }}
h2 {{ font-size: 16pt; letter-spacing: -0.01em; margin: 26px 0 8px; padding-top: 4px; border-top: 2px solid {INDIGO}; }}
h3 {{ font-size: 12pt; margin: 18px 0 6px; }}
h2, h3 {{ break-after: avoid; page-break-after: avoid; }}
h2 + p, h3 + p, h2 + table, h3 + table, h2 + figure, h3 + figure {{ break-before: avoid; page-break-before: avoid; }}
p, li {{ margin: 0 0 7px; }}
ul, ol {{ padding-left: 20px; margin: 0 0 10px; }}
code {{ font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 9pt; background: #f2f3f6; padding: 1px 4px; border-radius: 4px; }}
pre {{ font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 8.8pt; background: #f6f7f9; border: 1px solid {LINE}; border-radius: 8px; padding: 10px 12px; white-space: pre-wrap; }}
table {{ width: 100%; border-collapse: collapse; margin: 8px 0 14px; font-size: 9.5pt; page-break-inside: avoid; }}
th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid {LINE}; vertical-align: top; }}
th {{ background: #f6f7f9; font-weight: 600; }}
figure {{ margin: 12px 0 18px; page-break-inside: avoid; }}
figure svg {{ border: 1px solid {LINE}; border-radius: 10px; background: #fcfcfd; padding: 6px; }}
figure.shot img {{ width: 100%; border: 1px solid {LINE}; border-radius: 8px; }}
figcaption {{ font-size: 9pt; color: {MUTED}; margin-top: 5px; text-align: center; }}
.cover {{ height: 245mm; display: flex; flex-direction: column; justify-content: center; page-break-after: always; }}
.cover .tag {{ color: {INDIGO}; font-weight: 600; font-size: 12pt; margin-bottom: 10px; }}
.cover p.lead {{ font-size: 13pt; color: #3a3d45; max-width: 150mm; }}
.cover .meta {{ margin-top: 30px; color: {MUTED}; font-size: 10pt; }}
.box {{ border: 1px solid #aeb4ef; background: #eef0fd; border-radius: 10px; padding: 10px 14px; margin: 10px 0 14px; page-break-inside: avoid; }}
.warn {{ border-color: #f0c37a; background: #fff5e6; }}
.toc li {{ margin: 2px 0; }}
.break {{ page-break-before: always; }}
"""


def build_html() -> str:
    today = date.today().strftime("%B %Y")
    s: list[str] = []
    a = s.append

    a(f"""<div class="cover">
<div class="tag">Handoff document</div>
<h1>Tollgate</h1>
<p class="lead"><b>Every token pays the toll.</b> A self-hostable, OpenAI-compatible gateway that sits between
applications and AI models. It controls who may use the models and how much, avoids paying twice for the same
work, shares capacity fairly, and shows exactly what is happening.</p>
<p class="lead">This document explains the whole system in plain language: what it does, how a request moves
through it, how each feature works, how to run and operate it, and where everything lives in the code.</p>
<div class="meta">{today} · Backend: Python / FastAPI · Dashboard: Next.js · Data: Redis + Postgres · Models: Gemini API or Ollama</div>
</div>""")

    a("""<h2>Contents</h2><ol class="toc">
<li>What Tollgate is, in one page</li><li>Who uses it and how</li><li>The big picture</li>
<li>The life of a request</li><li>Features, explained</li><li>The dashboard</li><li>Accounts and security</li>
<li>Running it</li><li>Configuration you will actually touch</li><li>Observing it</li><li>Benchmarks</li>
<li>Where things live in the code</li><li>Day-to-day operations</li><li>Known limits and future work</li><li>Glossary</li></ol>""")

    a("""<h2 class="break">1. What Tollgate is, in one page</h2>
<p>Think of a toll gate on a road. Every car (a request from an app) passes through it. The gate checks the car is
allowed (an API key), makes sure it hasn't used the road too much today (limits and quotas), waves through cars it
already knows the answer for (the cache), lets cars going to exactly the same place travel together (coalescing),
and lets cars onto a narrow bridge in a fair order (the fair queue). Behind the gate is the road itself: an AI model.</p>
<p>Applications don't need to change. Tollgate speaks the same language as OpenAI's API, so an app only changes
one setting, its <code>base_url</code>, from OpenAI's address to Tollgate's. Everything else (the SDK, the code)
stays the same.</p>
<div class="box"><b>What makes it different</b>
<ul>
<li><b>A cache that doesn't bloat.</b> It stores an answer only when the same question comes back, so one-off
questions never fill it up.</li>
<li><b>Request coalescing.</b> If 50 identical questions arrive together, the model is asked once and all 50 get the
answer.</li>
<li><b>Fair queuing.</b> When the model is busy, the person who has received the least service goes next, so one
heavy script can't make everyone wait.</li>
<li><b>Proof.</b> Metrics, logs and dashboard pages show each of these working, and benchmarks measure them.</li>
</ul></div>
<p>It runs with one command (<code>docker compose up -d</code>). By default the models come from Google's Gemini API, so
the machine running Tollgate stays light; switching to fully local models with Ollama is one setting.</p>""")

    a("""<h2>2. Who uses it and how</h2>""")
    a(table(
        ["Person", "What they do"],
        [
            ["<b>Developer</b>", "Gets a key (<code>tg_live_...</code>) and points their OpenAI SDK, n8n, Open WebUI or script at Tollgate. Picks a model alias such as <code>fast</code> or <code>smart</code>."],
            ["<b>Operator / team lead</b>", "Runs Tollgate, creates and revokes keys, watches usage, cache efficiency, fairness and errors in the dashboard, and tests models in the Playground."],
            ["<b>Self-serve user</b> (optional)", "When accounts are switched on, signs in (Google, GitHub or email) and manages only their own keys and usage, within limits set by the operator."],
        ],
    ))

    a("""<h2 class="break">3. The big picture</h2>
<p>Tollgate is a handful of small services that Docker Compose starts together:</p>""")
    a(fig(d_architecture(), "Figure 1. Components. Solid arrows are the normal path; dashed arrows are optional or demo paths."))
    a(table(
        ["Part", "What it is for"],
        [
            ["Gateway (FastAPI)", "The heart. Handles every model request (<code>/v1</code>) and every management request (<code>/admin</code>)."],
            ["Dashboard (Next.js)", "The web app: landing page plus the operator console at <code>/dashboard</code>."],
            ["Redis: state", "Fast memory for key lookups, rate-limit counters and daily token usage. Never throws data away and is saved to disk."],
            ["Redis: cache", "A separate, memory-capped Redis that holds cached answers and evicts the least-used ones when full."],
            ["Postgres", "Durable storage for keys and the request log. Bundled locally, or a managed database such as Neon."],
            ["Models", "Google's Gemini API (default) or Ollama running open models locally. A mock model that always fails is included for demos."],
            ["Clerk (optional)", "Sign-in for teams. Without it, the dashboard is a single-user console that only answers on localhost."],
        ],
    ))

    a("""<h2 class="break">4. The life of a request</h2>
<p>When an app sends a question, it passes through seven steps. Each step can finish the request early, which is
what keeps the model from doing unnecessary work.</p>""")
    a(fig(d_pipeline(), "Figure 2. The request pipeline. Green boxes are shortcuts that avoid the model entirely."))
    a("""<ol>
<li><b>Auth.</b> The key is hashed and looked up in Redis (it falls back to the database only on a miss, and the
result is remembered for 60 seconds). Unknown or revoked keys get a 401.</li>
<li><b>Limits.</b> Two counters in one Redis round trip: requests this minute and tokens today. Over either: 429 with a
<code>Retry-After</code> header saying when to try again.</li>
<li><b>Cache lookup.</b> If the request is deterministic (temperature 0) and the same request was answered before, the
stored answer is returned in milliseconds.</li>
<li><b>Coalescing.</b> If an identical request is being answered right now, this one joins it instead of asking the
model again.</li>
<li><b>Fair queue.</b> Only genuinely new work gets here. It waits for one of the model's slots; the fairest request
goes next.</li>
<li><b>Model call.</b> The request goes to the model. If that model fails, is overloaded or is too slow, the next model
in the alias answers instead.</li>
<li><b>After the response.</b> Tokens are billed to the key, the answer may be cached, and a log entry is queued.</li>
</ol>
<p>Every response carries headers that tell the caller what happened: which model answered, whether it came from cache,
whether it was shared, how long it waited, and how much of the limit is left.</p>""")

    a("""<h2>5. Features, explained</h2>
<h3>5.1 API keys</h3>
<p>Keys look like <code>tg_live_</code> followed by 32 random characters. The full key is shown once, when it is created;
only a fingerprint (a SHA-256 hash) is stored, so even someone reading the database cannot use the keys. Revoking a key
takes effect immediately. Each key has its own requests-per-minute limit and daily token budget.</p>
<h3>5.2 Model aliases and fallback</h3>
<p>Apps ask for an alias, not a specific model. Each alias is a short list of models tried in order:</p>""")
    a(table(
        ["Alias", "Gemini API (default)", "Ollama (local)", "Notes"],
        [
            ["<code>fast</code>", "gemma-4-26b-a4b-it", "gemma3:1b", "Quick and cheap"],
            ["<code>smart</code>", "gemma-4-31b-it, then fast", "gemma3:4b, then gemma3:1b", "Falls back if the big model fails or is slow"],
            ["<code>smart-terse</code>", "like smart", "like smart", "Asks for the shortest correct answer"],
            ["<code>faq</code>", "like fast", "like fast", "Uses the shared cache pool"],
            ["<code>demo-failover</code>", "mock (always fails), then fast", "same", "Shows fallback working"],
        ],
    ))
    a("""<p>A <b>circuit breaker</b> protects the system from a model that keeps failing:</p>""")
    a(fig(d_breaker(), "Figure 3. Circuit breaker. A failing model is skipped for 30 seconds, then tested with a single request."))
    a("""<p>Gateway-side waiting (a full queue) is never counted as the model failing, so a busy period can't take a healthy
model offline.</p>
<h3>5.3 The cache that doesn't bloat</h3>
<p>Most questions are only ever asked once. A cache that stores everything fills up with them and throws out the answers
people actually reuse. Tollgate uses six layers of defense:</p>
<ol>
<li><b>Only deterministic, complete answers</b> are considered: temperature 0, the model finished normally, no tool
calls, and under 16 KB.</li>
<li><b>A precise key</b>: the question is normalized (extra spaces removed) and combined with the alias and the
caller's key, so different callers never share entries by accident.</li>
<li><b>Admission on second sight</b>: the first time a question is seen, only a tiny marker is kept. The answer is stored
the second time.</li>
<li><b>A separate, capped memory</b>: answers live in their own Redis that evicts the least-frequently-used entries, so
cache pressure can never wipe out rate-limit counters.</li>
<li><b>Scopes</b>: private per key by default; a shared pool (the <code>faq</code> alias) is opt-in, with a per-key
limit on how many new entries each key may add per minute.</li>
<li><b>Expiry</b>: entries expire after 24 hours.</li>
</ol>""")
    a(fig(d_cache_admission(), "Figure 4. Admission on second sight."))
    a("""<p>Streamed answers are cached too: they are assembled as they pass through and replayed as a fast stream later.</p>
<h3>5.4 Request coalescing</h3>""")
    a(fig(d_coalescing(), "Figure 5. Identical requests in flight share one model call."))
    a("""<p>Only requests that could be cached are coalesced, and only within one key. Each caller is billed for the tokens it
received. If two or more callers shared an answer, it is clearly popular, so it is cached straight away.</p>
<h3>5.5 Fair queuing</h3>
<p>A model can only work on a few requests at once (its <b>slots</b>). Normally the model server queues the rest first come,
first served, so one script sending 100 requests makes everyone else wait behind all of them. Tollgate takes that decision
away from the model server: it never sends more than the slot count and keeps the waiting line itself.</p>""")
    a(fig(d_fair_queue(), "Figure 6. The Virtual Token Counter picks the key that has received the least service."))
    a("""<p>This follows the published method <i>Fairness in Serving Large Language Models</i> (Sheng et al., OSDI 2024).</p>
<h3>5.6 Streaming</h3>
<p>Answers can stream word by word (Server-Sent Events). Tollgate relays the stream unchanged, counts tokens as they pass,
and still bills correctly if the client disconnects. If the model breaks mid-answer, the client receives an error event
and the failure is logged and counted.</p>
<h3>5.7 Terse mode</h3>
<p>The <code>smart-terse</code> alias adds an instruction to answer as briefly as possible. In one test it produced 85% fewer
output tokens for the same question.</p>
<h3>5.8 Logging and analytics</h3>""")
    a(fig(d_logging(), "Figure 7. Logs are written in batches so requests never wait for the database."))
    a("""<p>Each log entry records the key, alias, model used, tokens, latency, status, cache outcome, whether it was shared,
how long it waited for a slot, time to first token, and any cost tags sent with the request.</p>""")

    a("""<h2 class="break">6. The dashboard</h2>
<p>The dashboard has a light and a dark theme and a command menu (<code>Cmd/Ctrl + K</code>).</p>""")
    a(table(
        ["Page", "What it shows"],
        [
            ["Overview", "Requests, tokens, cache hit rate, error rate, latency, time to first token and model calls saved, each with the change from the previous period; a traffic chart; a year-long activity heatmap; status mix; latency distribution; usage by key, alias and model."],
            ["Keys", "Create (key shown once), list with today's usage, revoke."],
            ["Logs", "Every request with status, tokens, latency, time to first token, queue wait, and badges for cache, coalescing, fallback and tags. Filters by key, alias and status."],
            ["Cache", "Hit rate, stored entries, memory used against the limit, evictions, how many one-off prompts were kept out, and what happened to every request."],
            ["Fairness", "Live: model slots in use, requests waiting, each key's share of tokens and queue waits, its fairness counter, and Jain's fairness index."],
            ["Playground", "Chat with any alias through the gateway and see every header the gateway returned."],
        ],
    ))
    a(img("overview-light.png", "Overview page"))
    a(img("cache-light.png", "Cache page"))
    a(img("fairness-light.png", "Fairness page (live)"))
    a(img("landing-unique-light.png", "Landing page: what makes Tollgate different"))

    a("""<h2 class="break">7. Accounts and security</h2>""")
    a(fig(d_trust(), "Figure 8. Who trusts what."))
    a("""<ul>
<li><b>Keys</b> are random 190-bit secrets stored only as hashes. Unknown keys are briefly remembered as invalid, so random
guesses can't overload the database.</li>
<li><b>The admin token</b> is generated automatically on first start and never sent to a browser. The dashboard uses it
from its own server. The gateway refuses the public placeholder token in production.</li>
<li><b>Without Clerk</b>, the dashboard has no sign-in, so it only answers on <code>localhost</code>. That also blocks a
trick called DNS rebinding. The API and dashboard can be exposed separately, so sharing the API never exposes the
dashboard.</li>
<li><b>With Clerk</b>, each user sees only their own keys, logs and usage, and per-user caps protect the shared model
budget. If Clerk keys are added without rebuilding the dashboard, it refuses to run rather than opening up.</li>
<li><b>The shared cache pool is opt-in</b>: response timing could reveal that someone else asked the same thing, so cache
headers are hidden there and it is off by default.</li>
</ul>""")

    a("""<h2 class="break">8. Running it</h2>
<pre>git clone https://github.com/sumitsingh3072/tollgate.git
cd tollgate
cp .env.example .env          # paste a free Gemini key into GEMINI_API_KEY
docker compose up -d
# open http://localhost:3000</pre>""")
    a(fig(d_startup(), "Figure 9. Start-up order. Each service waits until the ones it needs are healthy."))
    a(table(
        ["Want", "Do this"],
        [
            ["Fully local models", "Set <code>UPSTREAM_PROVIDER=ollama</code> and run <code>docker compose --profile ollama up -d</code> (first start downloads about 4 GB)."],
            ["A managed database", "Set <code>DATABASE_URL</code> (for example a Neon connection string)."],
            ["Let other machines call the API", "Set <code>GATEWAY_BIND_ADDRESS=0.0.0.0</code> and put TLS in front."],
            ["Host the dashboard for a team", "Add Clerk keys, set <code>DASHBOARD_BIND_ADDRESS=0.0.0.0</code>, the public URLs, then <code>docker compose up -d --build</code>."],
            ["Stop", "<code>docker compose down</code> (data is kept in volumes)."],
        ],
    ))

    a("""<h2>9. Configuration you will actually touch</h2>""")
    a(table(
        ["Setting", "Default", "Meaning"],
        [
            ["GEMINI_API_KEY", "(empty)", "Key for the default model provider"],
            ["UPSTREAM_PROVIDER", "gemini", "gemini or ollama"],
            ["DATABASE_URL", "bundled Postgres", "Where keys and logs are stored"],
            ["ADMIN_TOKEN", "generated", "Set it only to call /admin yourself"],
            ["Clerk keys", "(empty)", "Turn on sign-in and per-user data"],
            ["UPSTREAM_MAX_PARALLEL", "4", "Requests per model at once; the rest wait fairly"],
            ["FAIR_MAX_QUEUE_PER_KEY / FAIR_MAX_WAIT_S", "20 / 30", "When waiting turns into a 429"],
            ["CACHE_TTL / CACHE_MAX_MEMORY", "24 h / 256 MB", "How long and how much to cache"],
            ["COALESCING_ENABLED", "true", "Share identical in-flight requests"],
            ["FALLBACK_TIMEOUT", "30 s", "How long to wait before trying the next model"],
            ["USER_MAX_KEYS / USER_MAX_RPM / USER_MAX_DAILY_TOKENS", "5 / 120 / 500,000", "Caps for signed-in users"],
        ],
    ))
    a("""<p>The full list with explanations is in <code>.env.example</code> and the README.</p>""")

    a("""<h2 class="break">10. Observing it</h2>
<ul>
<li><b>Response headers</b> on every answer: <code>x-tollgate-model</code>, <code>x-tollgate-cache</code>,
<code>x-tollgate-coalesce</code>, <code>x-tollgate-fallback</code>, <code>x-tollgate-queue-wait-ms</code>,
<code>x-ratelimit-*</code> and <code>x-request-id</code>.</li>
<li><b>Prometheus metrics</b> at <code>/metrics</code> (with the admin token): token usage, request duration, time to
first token, cache outcomes, coalesced requests, queue depth and queue wait. Names follow the OpenTelemetry GenAI
conventions.</li>
<li><b>Logs</b> are JSON lines, each carrying the request id, and every request is stored in the database.</li>
<li><b>Health</b>: <code>/health/live</code> says the process is up; <code>/health</code> checks Redis, the database
and the model provider, and drives the status light in the dashboard sidebar.</li>
</ul>
<p>Cost tags: apps can send <code>x-tollgate-tags: feature=search,team=growth</code>; the logs can then be filtered by tag.</p>""")

    a("""<h2>11. Benchmarks</h2>
<p>Measured with the scripts in <code>backend/bench</code> against a simulated model, so they are repeatable and free. Full
method in <code>docs/benchmarks.md</code>.</p>""")
    a(table(
        ["Test", "Without", "With"],
        [
            ["50 identical requests at once", "50 model calls, 6.61 s", "<b>1 model call, 0.56 s</b> (coalescing)"],
            ["A light user behind a heavy one (1 model slot)", "median wait 8.03 s", "<b>0.10 s</b> (fair queue)"],
            ["5,000 requests, 40% one-off, 2 MB cache", "607 entries, 2,943 evictions", "<b>277 entries, 413 evictions</b>, same hit rate"],
        ],
    ))
    a("""<div class="box warn"><b>Honest result.</b> In the shared-pool test, the per-key insert budget made the well-behaved
tenant's hit rate worse (40% to 35%), because the benchmark squeezes hours of traffic into seconds and the budget
throttled that tenant too. Admission plus LFU already protected it. The budget may still help against sustained real
floods but needs tuning to real traffic.</div>""")

    a("""<h2 class="break">12. Where things live in the code</h2>""")
    a(table(
        ["Path", "What is there"],
        [
            ["backend/app/main.py", "App start-up and shutdown, health checks, /metrics"],
            ["backend/app/api/v1.py", "The request pipeline for /v1/chat/completions"],
            ["backend/app/api/admin.py", "Keys, stats, logs, cache, coalescing, fairness, activity endpoints"],
            ["backend/app/core/cache.py", "Cache eligibility, keys, admission, scopes, stream replay"],
            ["backend/app/core/coalesce.py", "Flights: sharing identical in-flight requests"],
            ["backend/app/core/fair_queue.py", "Fair scheduler (Virtual Token Counter) and backpressure"],
            ["backend/app/core/fallback.py", "Alias chains, circuit breaker, fallback deadline"],
            ["backend/app/core/limits.py, keys.py", "Rate limits, quotas, key format and lookup cache"],
            ["backend/app/db/", "Tables, start-up migrations, queries and analytics"],
            ["backend/app/logging_queue.py", "Batched request logging"],
            ["backend/app/telemetry/metrics.py", "Prometheus metrics"],
            ["backend/bench/", "Benchmarks and the simulated model"],
            ["backend/tests/", "162 automated tests"],
            ["frontend/app/(marketing)/", "Landing page"],
            ["frontend/app/(app)/dashboard/", "Dashboard pages"],
            ["frontend/lib/server/gateway.ts", "The only place the admin token is used"],
            ["frontend/proxy.ts", "Sign-in and the localhost-only rule"],
            ["docker-compose.yml", "All services and how they start"],
            ["docs/", "Plan, architecture, phases, benchmarks, this document"],
        ],
    ))

    a("""<h2>13. Day-to-day operations</h2>""")
    a(table(
        ["Task", "How"],
        [
            ["Create or revoke a key", "Dashboard, Keys page (or POST / DELETE <code>/admin/keys</code>)"],
            ["See why a request was slow", "Logs page: latency, time to first token, queue wait, fallback badge; or search the gateway logs by <code>x-request-id</code>"],
            ["Model too busy (429 queue_full / queue_timeout)", "Raise <code>UPSTREAM_MAX_PARALLEL</code> if the provider allows, or slow the client"],
            ["Change models", "Set <code>GEMINI_*_MODEL</code> or <code>OLLAMA_*_MODEL</code>, then <code>docker compose up -d</code>"],
            ["Add an alias", "Edit <code>build_aliases</code> in <code>backend/app/config.py</code>"],
            ["Rebuild after changing Clerk keys or public URLs", "<code>docker compose up -d --build</code>"],
            ["Run the tests", "<code>cd backend && .venv/bin/pytest</code>; <code>cd frontend && pnpm lint && pnpm build</code>"],
            ["Back up", "Back up the Postgres database (keys and logs). The cache is disposable."],
        ],
    ))

    a("""<h2>14. Known limits and future work</h2>
<ul>
<li><b>One gateway process.</b> Coalescing and the fair queue live in the process's memory, so run a single gateway
process. Sharing them across several instances (through Redis) is future work.</li>
<li><b>No migration tool.</b> Schema changes are small additive steps applied at start-up; larger changes would need a
proper tool such as Alembic.</li>
<li><b>Per-key priority weights</b> are supported by the scheduler but not yet exposed in the dashboard.</li>
<li><b>Insert budgets</b> need tuning against real traffic (see the benchmark note).</li>
<li><b>Not yet built:</b> continuous integration, prebuilt container images, and a semantic (meaning-based) cache.</li>
</ul>""")

    a("""<h2>15. Glossary</h2>""")
    a(table(
        ["Term", "Meaning"],
        [
            ["Alias", "A friendly model name (fast, smart) that maps to a list of real models"],
            ["Coalescing", "Letting identical requests share one model call"],
            ["Leader / follower", "The request that calls the model / the ones that share its answer"],
            ["Slot", "One request the model can work on at a time"],
            ["VTC", "Virtual Token Counter: a running total of service each key has received"],
            ["Jain's index", "A fairness score from 1/n (one key got everything) to 1.0 (perfectly even)"],
            ["Admission", "Deciding whether an answer deserves cache space"],
            ["LFU", "Least Frequently Used: when memory is full, evict what is used least often"],
            ["TTFT", "Time to first token: how long until the first word of a streamed answer"],
            ["Circuit breaker", "Temporarily skipping a model that keeps failing"],
            ["SSE", "Server-Sent Events: how answers stream word by word"],
            ["Scope", "Who may share a cache entry: one key (private) or everyone (shared)"],
        ],
    ))
    return f"<!doctype html><html><head><meta charset='utf-8'><title>Tollgate handoff</title><style>{CSS}</style></head><body>{''.join(s)}</body></html>"


def main() -> None:
    html_path = HERE / "handoff.html"
    html_path.write_text(build_html())
    chrome = shutil.which("google-chrome") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome).exists():
        sys.exit(f"wrote {html_path}; install Google Chrome to render the PDF")
    pdf = HERE / "Tollgate-Handoff.pdf"
    subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", html_path.as_uri()],
        check=True,
        capture_output=True,
    )
    print(f"wrote {pdf}")


if __name__ == "__main__":
    main()
