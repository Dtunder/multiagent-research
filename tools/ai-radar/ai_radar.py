from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

import feedparser
import requests
import yaml

UTC = dt.timezone.utc
UA = "AI-Radar/1.0 (+local Hermes intelligence collector)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "application/json,text/plain,*/*"})


def load_env() -> None:
    """Load local environment variables if available."""
    candidates = [
        Path(__file__).parent / ".env",
        Path(os.path.expandvars(r"%LOCALAPPDATA%\hermes\.env")),
    ]
    for p in candidates:
        if p.exists():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass


load_env()


@dataclasses.dataclass
class Item:
    source: str
    title: str
    url: str
    published_at: str
    summary: str = ""
    author: str = ""
    metrics: dict[str, float] = dataclasses.field(default_factory=dict)
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)
    score: float = 0.0
    category: str = "Other"
    reason: str = ""
    item_id: str = ""

    def finalize(self) -> "Item":
        self.title = clean_text(self.title)
        self.summary = clean_text(self.summary)
        self.url = canonical_url(self.url)
        self.item_id = stable_id(self.source, self.url, self.title)
        return self

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class SourceError(RuntimeError):
    pass


def now_utc() -> dt.datetime:
    return dt.datetime.now(tz=UTC)


def parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        x = dt.datetime.fromisoformat(s)
        return x if x.tzinfo else x.replace(tzinfo=UTC)
    except ValueError:
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            x = dt.datetime.strptime(s, fmt)
            return x if x.tzinfo else x.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def iso(x: dt.datetime | None = None) -> str:
    x = x or now_utc()
    return x.astimezone(UTC).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlsplit(url.strip())
        if not p.scheme:
            return url.strip()
        keep = []
        for k, v in parse_qsl(p.query, keep_blank_values=True):
            lk = k.lower()
            if lk.startswith("utm_") or lk in {"ref", "ref_src", "source", "fbclid", "gclid", "si", "feature"}:
                continue
            keep.append((k, v))
        query = urlencode(keep, doseq=True)
        path = re.sub(r"/{2,}", "/", p.path or "/")
        if path != "/":
            path = path.rstrip("/")
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, query, ""))
    except Exception:
        return url.strip()


def stable_id(source: str, url: str, title: str) -> str:
    raw = f"{source}\n{url}\n{title}".encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:20]


def atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        cfg = yaml.safe_load(f) or {}
    if int(cfg.get("version", 0)) != 1:
        raise SystemExit("Unsupported config version; expected version: 1")
    return cfg


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "seen": {}, "last_run": None}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise SystemExit(f"State file is invalid: {exc}")


def save_state(path: Path, state: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))


def req_json(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 25) -> Any:
    r = SESSION.get(url, params=params, headers=headers or {}, timeout=timeout)
    if r.status_code >= 400:
        msg = clean_text(r.text)[:500]
        raise SourceError(f"HTTP {r.status_code}: {msg}")
    return r.json()


def fetch_arxiv(cfg: dict[str, Any], since: dt.datetime) -> list[Item]:
    out: list[Item] = []
    # If weekend (Sat=5, Sun=6) or Monday, widen lookback for arXiv because arXiv releases pause on weekends
    now = now_utc()
    arxiv_since = since
    if now.weekday() in (0, 5, 6):
        arxiv_since = min(since, now - dt.timedelta(hours=60))

    # 1. Check configured RSS feeds
    for feed in cfg.get("feeds", []):
        try:
            parsed = feedparser.parse(feed)
            for e in parsed.entries:
                published = parse_time(getattr(e, "published", None) or getattr(e, "updated", None))
                if published and published < arxiv_since:
                    continue
                out.append(Item(
                    source="arxiv",
                    title=getattr(e, "title", ""),
                    url=getattr(e, "link", ""),
                    published_at=iso(published or now_utc()),
                    summary=getattr(e, "summary", ""),
                    author=getattr(e, "author", ""),
                    metadata={"feed": feed},
                ).finalize())
        except Exception:
            pass

    # 2. If feeds yielded few or no items (e.g. weekend lull or quiet feed), query official arXiv API
    if len(out) < 5:
        try:
            api_url = "http://export.arxiv.org/api/query"
            params = {
                "search_query": "cat:cs.AI OR cat:cs.CL OR cat:cs.LG",
                "start": 0,
                "max_results": 25,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
            resp = SESSION.get(api_url, params=params, timeout=25)
            if resp.status_code == 200:
                parsed = feedparser.parse(resp.content)
                for e in parsed.entries:
                    published = parse_time(getattr(e, "published", None) or getattr(e, "updated", None))
                    if published and published < arxiv_since:
                        continue
                    out.append(Item(
                        source="arxiv",
                        title=getattr(e, "title", ""),
                        url=getattr(e, "link", ""),
                        published_at=iso(published or now_utc()),
                        summary=getattr(e, "summary", ""),
                        author=getattr(e, "author", ""),
                        metadata={"feed": "arxiv_api"},
                    ).finalize())
        except Exception as exc:
            if not out:
                raise SourceError(f"arXiv API error: {exc}")
    return out


def fetch_hackernews(cfg: dict[str, Any], queries: list[str], since: dt.datetime) -> list[Item]:
    out: list[Item] = []
    cutoff = int(since.timestamp())
    limit = int(cfg.get("max_per_query", 25))
    for q in queries:
        data = req_json("https://hn.algolia.com/api/v1/search_by_date", params={
            "query": q,
            "tags": "story",
            "numericFilters": f"created_at_i>{cutoff}",
            "hitsPerPage": min(100, limit),
        })
        for h in data.get("hits", []):
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            out.append(Item(
                source="hackernews",
                title=h.get("title") or "",
                url=url,
                published_at=h.get("created_at") or iso(),
                summary="",
                author=h.get("author") or "",
                metrics={"points": float(h.get("points") or 0), "comments": float(h.get("num_comments") or 0)},
                metadata={"hn_id": h.get("objectID"), "query": q},
            ).finalize())
    return out


def get_github_token(cfg: dict[str, Any]) -> str:
    # 1. Try gh auth token first (active validated CLI keyring token)
    try:
        clean_env = os.environ.copy()
        clean_env.pop("GH_TOKEN", None)
        clean_env.pop("GITHUB_TOKEN", None)
        gh_cmd = shutil.which("gh") or shutil.which("gh.exe") or r"C:\Program Files\GitHub CLI\gh.exe"
        res = subprocess.run([gh_cmd, "auth", "token"], capture_output=True, text=True, timeout=5, env=clean_env)
        if res.returncode == 0 and res.stdout.strip():
            tok = res.stdout.strip()
            if tok.startswith("gho_") or tok.startswith("ghp_"):
                return tok
    except Exception:
        pass
    # 2. Try configured environment variable
    token_env = str(cfg.get("token_env", "GITHUB_TOKEN"))
    token = os.getenv(token_env, "").strip()
    if not token and token_env != "GH_TOKEN":
        token = os.getenv("GH_TOKEN", "").strip()
    return token


def fetch_github(cfg: dict[str, Any], queries: list[str], since: dt.datetime) -> list[Item]:
    out: list[Item] = []
    token = get_github_token(cfg)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    max_per = min(100, int(cfg.get("max_per_query", 20)))
    date = since.date().isoformat()
    for q in queries:
        search = f'{q} in:name,description,readme pushed:>={date}'
        try:
            data = req_json("https://api.github.com/search/repositories", params={
                "q": search,
                "sort": "updated",
                "order": "desc",
                "per_page": max_per,
            }, headers=headers)
        except SourceError as exc:
            # Fallback to public unauthenticated if auth token returned 401
            if "401" in str(exc) and token:
                data = req_json("https://api.github.com/search/repositories", params={
                    "q": search,
                    "sort": "updated",
                    "order": "desc",
                    "per_page": min(10, max_per),
                }, headers={"Accept": "application/vnd.github+json", "User-Agent": UA})
            else:
                raise
        for r in data.get("items", []):
            pushed = parse_time(r.get("pushed_at")) or parse_time(r.get("updated_at")) or now_utc()
            if pushed < since:
                continue
            out.append(Item(
                source="github",
                title=r.get("full_name") or r.get("name") or "",
                url=r.get("html_url") or "",
                published_at=iso(pushed),
                summary=r.get("description") or "",
                author=(r.get("owner") or {}).get("login") or "",
                metrics={"stars": float(r.get("stargazers_count") or 0), "forks": float(r.get("forks_count") or 0)},
                metadata={"language": r.get("language"), "topics": r.get("topics", []), "query": q},
            ).finalize())
    return out


def fetch_huggingface(cfg: dict[str, Any], since: dt.datetime) -> list[Item]:
    token = os.getenv(str(cfg.get("token_env", "HF_TOKEN")), "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    limit = min(500, int(cfg.get("limit", 100)))
    data = req_json("https://huggingface.co/api/models", params={"sort": "lastModified", "direction": "-1", "limit": limit, "full": "true"}, headers=headers)
    out: list[Item] = []
    for m in data:
        modified = parse_time(m.get("lastModified")) or now_utc()
        if modified < since:
            continue
        model_id = m.get("modelId") or m.get("id") or ""
        card = m.get("cardData") or {}
        tags = m.get("tags") or []
        out.append(Item(
            source="huggingface",
            title=model_id,
            url=f"https://huggingface.co/{model_id}" if model_id else "",
            published_at=iso(modified),
            summary=card.get("model_description") if isinstance(card, dict) else "",
            author=(model_id.split("/", 1)[0] if "/" in model_id else ""),
            metrics={"downloads": float(m.get("downloads") or 0), "likes": float(m.get("likes") or 0)},
            metadata={"pipeline_tag": m.get("pipeline_tag"), "tags": tags},
        ).finalize())
    return out


def fetch_youtube(cfg: dict[str, Any], queries: list[str], since: dt.datetime) -> list[Item]:
    key = os.getenv(str(cfg.get("api_key_env", "YOUTUBE_API_KEY")), "").strip()
    if not key:
        raise SourceError("YOUTUBE_API_KEY is not configured")
    out: list[Item] = []
    per = min(50, int(cfg.get("max_per_query", 10)))
    published_after = iso(since)
    for q in queries:
        data = req_json("https://www.googleapis.com/youtube/v3/search", params={
            "part": "snippet",
            "type": "video",
            "order": "date",
            "q": q,
            "publishedAfter": published_after,
            "maxResults": per,
            "key": key,
        })
        for it in data.get("items", []):
            vid = (it.get("id") or {}).get("videoId")
            if not vid:
                continue
            sn = it.get("snippet") or {}
            published = parse_time(sn.get("publishedAt")) or now_utc()
            out.append(Item(
                source="youtube",
                title=sn.get("title") or "",
                url=f"https://www.youtube.com/watch?v={vid}",
                published_at=iso(published),
                summary=sn.get("description") or "",
                author=sn.get("channelTitle") or "",
                metadata={"channel_id": sn.get("channelId"), "query": q},
            ).finalize())
    return out


def fetch_x(cfg: dict[str, Any], queries: list[str], since: dt.datetime) -> list[Item]:
    token = os.getenv(str(cfg.get("bearer_token_env", "X_BEARER_TOKEN")), "").strip()
    if not token:
        raise SourceError("X_BEARER_TOKEN is not configured")
    out: list[Item] = []
    max_results = max(10, min(100, int(cfg.get("max_results", 50))))
    start_time = iso(since)
    query_str = "(" + " OR ".join(f'"{q}"' for q in queries[:5]) + ") -is:retweet lang:en"
    params = {
        "query": query_str,
        "max_results": max_results,
        "start_time": start_time,
        "tweet.fields": "created_at,public_metrics,lang",
        "expansions": "author_id",
        "user.fields": "username,verified",
    }
    data = req_json("https://api.x.com/2/tweets/search/recent", params=params, headers={"Authorization": f"Bearer {token}"})
    users = {u.get("id"): u for u in (data.get("includes") or {}).get("users", [])}
    for t in data.get("data", []):
        tid = t.get("id")
        u = users.get(t.get("author_id")) or {}
        username = u.get("username") or "i"
        metrics = t.get("public_metrics") or {}
        out.append(Item(
            source="x",
            title=clean_text(t.get("text", ""))[:140],
            url=f"https://x.com/{username}/status/{tid}",
            published_at=t.get("created_at") or iso(),
            summary=t.get("text") or "",
            author=username,
            metrics={
                "likes": float(metrics.get("like_count") or 0),
                "reposts": float(metrics.get("retweet_count") or 0),
                "replies": float(metrics.get("reply_count") or 0),
            },
            metadata={"lang": t.get("lang"), "verified": bool(u.get("verified"))},
        ).finalize())
    return out


def fetch_rss(cfg: dict[str, Any], since: dt.datetime) -> list[Item]:
    out: list[Item] = []
    for feed in cfg.get("feeds", []):
        parsed = feedparser.parse(feed)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise SourceError(f"Could not parse RSS feed {feed}: {getattr(parsed, 'bozo_exception', 'unknown error')}")
        source_name = clean_text(getattr(parsed.feed, "title", "RSS")) or "RSS"
        for e in parsed.entries:
            published = parse_time(getattr(e, "published", None) or getattr(e, "updated", None))
            if published and published < since:
                continue
            out.append(Item(
                source="rss",
                title=getattr(e, "title", ""),
                url=getattr(e, "link", ""),
                published_at=iso(published or now_utc()),
                summary=getattr(e, "summary", ""),
                author=getattr(e, "author", ""),
                metadata={"feed": feed, "feed_title": source_name},
            ).finalize())
    return out


def token_set(text: str) -> set[str]:
    text = text.lower().replace("-", " ").replace("_", " ")
    raw = [x for x in re.findall(r"[a-z0-9][a-z0-9+.]{1,}", text) if len(x) > 2]
    out: set[str] = set()
    for x in raw:
        y = x
        for suffix in ("ing", "ed", "es", "s"):
            if y.endswith(suffix) and len(y) - len(suffix) >= 4:
                y = y[:-len(suffix)]
                break
        out.add(y)
    return out


def title_similarity(a: str, b: str) -> float:
    aa, bb = token_set(a), token_set(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)


def dedupe(items: list[Item], threshold: float) -> list[Item]:
    by_url: dict[str, Item] = {}
    for x in sorted(items, key=lambda z: z.published_at, reverse=True):
        key = x.url or x.item_id
        if key in by_url:
            if sum(x.metrics.values()) > sum(by_url[key].metrics.values()):
                by_url[key] = x
        else:
            by_url[key] = x
    uniq = list(by_url.values())
    kept: list[Item] = []
    for x in sorted(uniq, key=lambda z: z.published_at, reverse=True):
        duplicate_of = None
        for y in kept:
            if title_similarity(x.title, y.title) >= threshold:
                duplicate_of = y
                break
        if duplicate_of:
            duplicate_of.metadata.setdefault("duplicate_sources", []).append({"source": x.source, "url": x.url})
            for k, v in x.metrics.items():
                duplicate_of.metrics[k] = max(float(duplicate_of.metrics.get(k, 0)), float(v))
        else:
            kept.append(x)
    return kept


CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("Agents", ("agent", "agentic", "tool use", "computer use", "browser use", "mcp", "subagent", "multi-agent")),
    ("Coding", ("coding", "code model", "software engineering", "developer", "repository", "copilot", "program synthesis", "swe-bench")),
    ("Reasoning", ("reasoning", "test-time", "test time", "chain of thought", "inference scaling", "search", "tree of thought")),
    ("New Models", ("foundation model", "llm release", "new model", "weights released", "model release", "weights", "llama", "deepseek", "qwen", "mistral", "gemma", "claude 3", "gpt-4", "gemini 1.", "gemini 2.", "gemini 3.")),
    ("Robotics", ("robot", "robotics", "embodied", "physical ai", "actuator", "humanoid", "manipulation", "quadruped")),
    ("Multimodal", ("multimodal", "vision language", "vlm", "audio", "video model", "image model", "diffusion", "text-to-image", "text-to-video", "speech")),
    ("Open Source", ("open source", "open-source", "open weights", "apache 2.0", "mit license", "hugging face release")),
    ("Papers", ("paper", "arxiv", "preprint", "published in", "proceedings")),
    ("Benchmarks", ("benchmark", "eval", "evaluation", "leaderboard", "arena", "metric", "humaneval", "mmlu", "gsm8k")),
    ("APIs", ("api", "endpoint", "sdk", "developer platform", "rate limit", "token pricing", "context window")),
    ("Tools", ("tool", "library", "framework", "package", "cli", "extension", "plugin", "runtime")),
    ("Business", ("startup", "funding", "acquisition", "enterprise", "market", "revenue", "partnership")),
    ("Manufacturing", ("manufacturing", "cad", "cnc", "industrial", "fabrication", "assembly", "inspection", "hardware")),
    ("Scheduling / Optimization", ("scheduling", "optimization", "linear programming", "mcts", "constraint", "operations research", "planner")),
    ("Research Ideas", ("idea", "hypothesis", "conjecture", "future work", "proposal", "research direction")),
    ("Research", ("research", "study", "experiment", "findings", "dataset", "reinforcement learning", "rl", "fine-tuning")),
]


def classify(item: Item) -> str:
    hay = f"{item.title} {item.summary} {' '.join(map(str, item.metadata.get('tags', [])))}".lower()
    for cat, words in CATEGORIES:
        if any(w in hay for w in words):
            return cat
    return "Other"


SOURCE_CRED = {
    "arxiv": 1.00,
    "github": 0.88,
    "huggingface": 0.90,
    "rss": 0.82,
    "x": 0.62,
    "youtube": 0.62,
    "hackernews": 0.55,
}


def relevance_score(item: Item, queries: list[str], watch_domains: list[str]) -> float:
    hay = f"{item.title} {item.summary}".lower()
    terms: set[str] = set()
    for q in queries:
        terms |= token_set(q)
    hits = sum(1 for t in terms if t in hay)
    base = min(1.0, hits / max(3.0, min(8.0, len(terms) / 3.0)))
    host = urlsplit(item.url).netloc.lower()
    watch = 1.0 if any(host == d or host.endswith("." + d) for d in watch_domains) else 0.0
    return min(1.0, base * 0.8 + watch * 0.2)


def momentum_score(item: Item) -> float:
    m = item.metrics
    weighted = (
        float(m.get("stars", 0)) * 2.0
        + float(m.get("forks", 0)) * 1.5
        + float(m.get("downloads", 0)) * 0.01
        + float(m.get("likes", 0)) * 1.0
        + float(m.get("reposts", 0)) * 2.0
        + float(m.get("replies", 0)) * 0.5
        + float(m.get("points", 0)) * 1.0
        + float(m.get("comments", 0)) * 0.5
    )
    return min(1.0, math.log1p(max(0.0, weighted)) / math.log(1001.0))


def score_item(item: Item, queries: list[str], watch_domains: list[str], seen: dict[str, Any], now: dt.datetime) -> Item:
    rel = relevance_score(item, queries, watch_domains)
    cred = SOURCE_CRED.get(item.source, 0.5)
    published = parse_time(item.published_at) or now
    age_h = max(0.0, (now - published).total_seconds() / 3600.0)
    recency = max(0.0, 1.0 - age_h / 36.0)
    novelty = 0.0 if item.item_id in seen else 1.0
    momentum = momentum_score(item)
    score = 35 * rel + 25 * cred + 20 * recency + 10 * novelty + 10 * momentum
    item.score = round(score, 1)
    item.category = classify(item)
    reasons = []
    if rel >= 0.6:
        reasons.append("high topic match")
    if cred >= 0.85:
        reasons.append("strong primary/technical source")
    if recency >= 0.7:
        reasons.append("very recent")
    if momentum >= 0.4:
        reasons.append("visible momentum")
    if novelty:
        reasons.append("new to radar")
    item.reason = ", ".join(reasons) or "moderate relevance"
    return item


def render_brief(date: str, items: list[Item], source_status: dict[str, dict[str, Any]], deep_threshold: float, limit: int) -> str:
    top = sorted(items, key=lambda x: (x.score, x.published_at), reverse=True)[:limit]
    
    # Executive Summary computation
    counts = Counter(x.category for x in top)
    top_categories = ", ".join(f"{cat} ({n})" for cat, n in counts.most_common(3)) or "Allgemein"
    deep_count = sum(1 for x in top if x.score >= deep_threshold)
    
    lines = [
        f"# AI Daily Briefing — {date}",
        "",
        "## Executive Summary",
        "",
        f"- **Erfassungszeitpunkt**: {iso()}",
        f"- **Gefilterte Relevante Events**: {len(items)} (Top {len(top)} im Briefing)",
        f"- **Schwerpunkte**: {top_categories}",
        f"- **Deep Analysis Kandidaten**: {deep_count} Events über Schwellenwert ({deep_threshold})",
        "",
        "## Top Developments",
        "",
    ]
    
    if not top:
        lines += ["Keine qualifizierten neuen KI-Entwicklungen im aktuellen Zeitfenster erfasst.", ""]
    else:
        for i, x in enumerate(top, 1):
            cred = SOURCE_CRED.get(x.source, 0.5)
            conf_str = "Hoch" if cred >= 0.85 else ("Mittel" if cred >= 0.60 else "Basis")
            dupes = x.metadata.get("duplicate_sources") or []
            supporting_str = f"{len(dupes)} zusätzliche Signale" if dupes else "Keine weiteren Duplikate"
            
            repo_or_paper = "Kein Direktlink"
            if x.source == "arxiv" or "arxiv.org" in x.url:
                repo_or_paper = f"Paper: [{x.url}]({x.url})"
            elif x.source == "github" or "github.com" in x.url:
                repo_or_paper = f"Repository: [{x.url}]({x.url})"
            elif x.source == "huggingface" or "huggingface.co" in x.url:
                repo_or_paper = f"Model/Dataset: [{x.url}]({x.url})"
            elif x.url:
                repo_or_paper = f"Link: [{x.url}]({x.url})"

            lines.append(f"### {i}. {x.title}")
            lines.append(f"- **Kurze Zusammenfassung**: {x.summary[:420] if x.summary else 'Keine Beschreibung vorhanden.'}")
            lines.append(f"- **Warum relevant**: {x.reason}")
            lines.append(f"- **Primäre Quelle**: {x.source} — [{x.url}]({x.url})")
            lines.append(f"- **Supporting Sources**: {supporting_str}")
            lines.append(f"- **Kategorie**: {x.category}")
            lines.append(f"- **Confidence**: {conf_str} ({cred:.2f})")
            lines.append(f"- **Score**: **{x.score}/100**")
            lines.append(f"- **Repository/Paper/Model**: {repo_or_paper}")
            if x.score >= deep_threshold:
                lines.append("- **Deep Analysis**: **In Warteschlange aufgenommen**")
            lines.append("")

    # Specific category sections
    cat_sections = [
        ("New Models", ["New Models", "Models"]),
        ("Agents", ["Agents"]),
        ("Coding", ["Coding"]),
        ("Robotics / Automation", ["Robotics"]),
        ("Research", ["Research", "Benchmarks", "APIs", "Manufacturing", "Scheduling / Optimization"]),
        ("Important Papers", ["Papers"]),
        ("Tools Worth Testing", ["Tools", "Open Source"]),
        ("Research / Project Ideas", ["Research Ideas"]),
    ]

    for section_title, target_cats in cat_sections:
        cat_items = [x for x in top if x.category in target_cats]
        lines.append(f"## {section_title}")
        lines.append("")
        if not cat_items:
            lines.append(f"Keine spezifischen Funde für {section_title} in diesem Lauf.")
        else:
            for it in cat_items[:5]:
                lines.append(f"- **[{it.title}]({it.url})** (Score: {it.score}, Quelle: {it.source})")
                if it.summary:
                    lines.append(f"  {it.summary[:180]}...")
        lines.append("")

    # Rumors / Unconfirmed
    rumors = [x for x in top if SOURCE_CRED.get(x.source, 0.5) < 0.65 or "rumor" in x.title.lower()]
    lines.append("## Rumors / Unconfirmed")
    lines.append("")
    if not rumors:
        lines.append("Keine unbestätigten Gerüchte erfasst.")
    else:
        for r in rumors[:3]:
            lines.append(f"- **[{r.title}]({r.url})** (Quelle: {r.source}, Score: {r.score})")
    lines.append("")

    # Source Health
    lines.append("## Source Health")
    lines.append("")
    for source in sorted(source_status):
        st = source_status[source]
        if st.get("ok"):
            lines.append(f"- **{source}**: OK — {st.get('count', 0)} Rohdaten-Elemente erfasst")
        else:
            lines.append(f"- **{source}**: {st.get('error', 'unbekannter Fehler')}")
    lines.append("")

    # Category Pulse
    lines.append("## Category Pulse")
    lines.append("")
    for cat, n in counts.most_common():
        lines.append(f"- {cat}: {n}")
    lines.append("")
    lines.append("---")
    lines.append("Generiert durch AI Radar v1. Rohdaten und Protokolle sind persistent gespeichert.")
    lines.append("")
    return "\n".join(lines)


def source_enabled(cfg: dict[str, Any], name: str) -> bool:
    return bool((cfg.get("sources", {}).get(name) or {}).get("enabled", False))


def collect(config_path: Path, enforce_window: bool) -> int:
    cfg = load_yaml(config_path)
    tz_name = cfg.get("timezone", "Europe/Berlin")
    try:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = UTC
    now = now_utc()
    local_now = now.astimezone(local_tz)
    window = cfg.get("window") or {}
    start_h = int(window.get("start_hour", 2))
    end_h = int(window.get("end_hour", 8))
    if enforce_window and not (start_h <= local_now.hour <= end_h):
        print(json.dumps({"status": "outside_window", "local_time": local_now.isoformat(), "window": [start_h, end_h]}))
        return 0

    root = Path(os.path.expandvars(str(cfg["output_root"])))
    for d in ("DAILY", "RAW", "STATE", "LOGS", "CONFIG", "KNOWLEDGE_BASE"):
        (root / d).mkdir(parents=True, exist_ok=True)
    state_path = root / "STATE" / "state.json"
    state = load_state(state_path)
    ranking = cfg.get("ranking") or {}
    lookback_h = float(ranking.get("lookback_hours", 30))
    since = now - dt.timedelta(hours=lookback_h)
    last_run = parse_time(state.get("last_run"))
    if last_run:
        since = max(since, last_run - dt.timedelta(minutes=20))
    queries = [str(q) for q in cfg.get("queries", []) if str(q).strip()]
    watch_domains = [str(x).lower() for x in (cfg.get("watchlist") or {}).get("domains", [])]

    raw_by_source: dict[str, list[Item]] = {}
    status: dict[str, dict[str, Any]] = {}
    source_cfg = cfg.get("sources") or {}

    fetchers = {
        "arxiv": lambda: fetch_arxiv(source_cfg.get("arxiv") or {}, since),
        "hackernews": lambda: fetch_hackernews(source_cfg.get("hackernews") or {}, queries, since),
        "github": lambda: fetch_github(source_cfg.get("github") or {}, queries, since),
        "huggingface": lambda: fetch_huggingface(source_cfg.get("huggingface") or {}, since),
        "youtube": lambda: fetch_youtube(source_cfg.get("youtube") or {}, queries, since),
        "x": lambda: fetch_x(source_cfg.get("x") or {}, queries, since),
        "rss": lambda: fetch_rss(source_cfg.get("rss") or {}, since),
    }

    for name, fn in fetchers.items():
        if not source_enabled(cfg, name):
            if name == "youtube" and not os.getenv(str(source_cfg.get("youtube", {}).get("api_key_env", "YOUTUBE_API_KEY")), "").strip():
                status[name] = {"ok": False, "error": "disabled_missing_credentials"}
            elif name == "x" and not os.getenv(str(source_cfg.get("x", {}).get("bearer_token_env", "X_BEARER_TOKEN")), "").strip():
                status[name] = {"ok": False, "error": "disabled_missing_credentials"}
            else:
                status[name] = {"ok": False, "error": "disabled"}
            continue
        try:
            rows = fn()
            raw_by_source[name] = rows
            status[name] = {"ok": True, "count": len(rows)}
        except Exception as exc:
            status[name] = {"ok": False, "error": clean_text(exc)[:600]}
            raw_by_source[name] = []

    date = local_now.date().isoformat()
    raw_dir = root / "RAW" / date
    raw_dir.mkdir(parents=True, exist_ok=True)
    for source, rows in raw_by_source.items():
        atomic_write(raw_dir / f"{source}.jsonl", "".join(json.dumps(x.as_dict(), ensure_ascii=False, sort_keys=True) + "\n" for x in rows))

    all_items = [x for rows in raw_by_source.values() for x in rows if x.title and x.url]
    unique = dedupe(all_items, float(ranking.get("dedupe_similarity", 0.78)))
    scored = [score_item(x, queries, watch_domains, state.get("seen", {}), now) for x in unique]
    qualified = [x for x in scored if x.score >= float(ranking.get("min_score", 34))]
    qualified.sort(key=lambda x: (x.score, x.published_at), reverse=True)

    deep_threshold = float(ranking.get("deep_analysis_score", 68))
    deep = [x.as_dict() for x in qualified if x.score >= deep_threshold and x.item_id not in state.get("seen", {})]
    atomic_write(root / "NEEDS_DEEP_ANALYSIS.json", json.dumps({
        "generated_at": iso(now),
        "threshold": deep_threshold,
        "items": deep,
    }, ensure_ascii=False, indent=2, sort_keys=True))

    brief = render_brief(date, qualified, status, deep_threshold, int(ranking.get("max_brief_items", 20)))
    atomic_write(root / "DAILY" / f"{date}_AI_Daily_Briefing.md", brief)

    kb_path = root / "KNOWLEDGE_BASE" / "events.jsonl"
    new_for_kb = []
    seen = state.setdefault("seen", {})
    for x in qualified:
        if x.item_id not in seen:
            new_for_kb.append(x.as_dict())
        seen[x.item_id] = {"first_seen": seen.get(x.item_id, {}).get("first_seen", iso(now)), "last_seen": iso(now), "url": x.url, "title": x.title}
    append_jsonl(kb_path, new_for_kb)

    cutoff = now - dt.timedelta(days=90)
    state["seen"] = {k: v for k, v in seen.items() if (parse_time(v.get("last_seen")) or now) >= cutoff}
    state["last_run"] = iso(now)
    state["last_summary"] = {"raw": len(all_items), "unique": len(unique), "qualified": len(qualified), "deep": len(deep)}
    save_state(state_path, state)

    log_row = {
        "at": iso(now),
        "local_time": local_now.isoformat(),
        "status": "ok",
        "counts": state["last_summary"],
        "sources": status,
        "brief": str(root / "DAILY" / f"{date}_AI_Daily_Briefing.md"),
    }
    append_jsonl(root / "LOGS" / f"{date}.jsonl", [log_row])
    print(json.dumps(log_row, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Quota-efficient nightly AI intelligence collector")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("collect", "nightly"):
        sp = sub.add_parser(name)
        sp.add_argument("--config", required=True, type=Path)
    args = p.parse_args(argv)
    if args.cmd == "collect":
        return collect(args.config, enforce_window=False)
    return collect(args.config, enforce_window=True)


if __name__ == "__main__":
    raise SystemExit(main())
