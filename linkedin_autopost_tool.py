import argparse
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from dotenv import load_dotenv

load_dotenv()


TOPICS = {
    "management": {
        "angles": [
            "leadership under ambiguity",
            "managing performance without micromanagement",
            "decision-making frameworks",
            "turning chaos into execution",
            "coaching vs controlling",
        ],
        "hashtags": ["#Leadership", "#Management", "#Strategy", "#Execution"],
    },
    "consulting": {
        "angles": [
            "how consultants diagnose the real problem",
            "why most recommendations fail",
            "client alignment and incentives",
            "scope discipline and deliverables",
            "measuring outcomes, not outputs",
        ],
        "hashtags": ["#Consulting", "#BusinessStrategy", "#Operations", "#Transformation"],
    },
    "ai_in_business": {
        "angles": [
            "where AI actually pays off",
            "AI adoption without hype",
            "process automation vs copilots",
            "governance, risk, and ROI",
            "AI literacy for leaders",
        ],
        "hashtags": ["#AI", "#Productivity", "#Innovation", "#Business"],
    },
    "productivity_leadership_strategy": {
        "angles": [
            "personal productivity as a leadership skill",
            "systems thinking for execution",
            "strategy as constraint management",
            "meeting design and decision hygiene",
            "building momentum with small bets",
        ],
        "hashtags": ["#Productivity", "#Leadership", "#Strategy", "#Focus"],
    },
}


HOOK_TOKENS = [
    "Stop",
    "Most",
    "Here's why",
    "Nobody tells you",
    "The uncomfortable truth",
    "Hot take",
    "If I had to start again",
    "Quick question",
    "Contrary to popular belief",
]


def _clean_post(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    # Remove common wrappers
    text = re.sub(r"^\s*(POST:|LinkedIn Post:)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*(/POST|\[/POST\])\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _first_two_lines(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[:2]) if lines else text[:120]


def _sentence_stats(text: str) -> Tuple[float, int]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s for s in sentences if s]
    if not sentences:
        return 999.0, 0
    words = [len(s.split()) for s in sentences]
    avg = sum(words) / len(words)
    return avg, len(sentences)


def score_post(text: str, topic_key: str) -> Dict[str, float]:
    cleaned = _clean_post(text)
    words = cleaned.split()
    word_count = len(words)
    first2 = _first_two_lines(cleaned).lower()

    hook = 0.0
    if "?" in first2:
        hook += 2.0
    if any(tok.lower() in first2 for tok in [t.lower() for t in HOOK_TOKENS]):
        hook += 2.0
    if re.search(r"\b\d+\b", first2):
        hook += 1.2
    if any(k in first2 for k in ["stop", "most", "uncomfortable", "hot take", "nobody tells"]):
        hook += 1.0

    structure = 0.0
    paragraphs = [p for p in cleaned.split("\n\n") if p.strip()]
    if 3 <= len(paragraphs) <= 6:
        structure += 1.2
    if len(paragraphs) >= 2:
        structure += 0.4

    clarity = 0.0
    avg_sentence_len, _ = _sentence_stats(cleaned)
    if 8 <= avg_sentence_len <= 18:
        clarity += 2.0
    elif avg_sentence_len < 8:
        clarity += 0.8
    elif avg_sentence_len > 24:
        clarity -= 1.0
    if "because" in cleaned.lower() or "so " in cleaned.lower():
        clarity += 0.8

    story = 0.0
    if any(k in cleaned.lower() for k in ["i used to", "last year", "we tried", "my team", "in practice", "during the", "i learned"]):
        story += 1.0

    cta = 0.0
    last_line = cleaned.splitlines()[-1].strip().lower() if cleaned.splitlines() else ""
    if "?" in last_line or last_line.startswith("what ") or last_line.startswith("how "):
        cta += 1.4
    if any(k in cleaned.lower() for k in ["share", "comment", "reply", "tell me"]):
        cta += 0.6

    length = 0.0
    if 110 <= word_count <= 230:
        length += 2.0
    elif 230 < word_count <= 280:
        length += 0.4
    else:
        length -= 0.6

    topic_bonus = 0.0
    topic = TOPICS.get(topic_key, {})
    if topic and topic.get("angles"):
        angles = topic["angles"]
        # Light keyword overlap
        overlap = 0
        lowered = cleaned.lower()
        for a in angles:
            token = a.split()[0].lower()
            if token in lowered:
                overlap += 1
        topic_bonus = min(1.5, overlap * 0.3)

    total = hook + structure + clarity + story + cta + length + topic_bonus
    return {
        "total": total,
        "hook": hook,
        "structure": structure,
        "clarity": clarity,
        "story": story,
        "cta": cta,
        "length": length,
        "topic_bonus": topic_bonus,
        "word_count": float(word_count),
    }


def _fallback_generate(topic_key: str) -> str:
    cfg = TOPICS[topic_key]
    angle = random.choice(cfg["angles"])
    hook = random.choice(HOOK_TOKENS)
    themes = {
        "management": [
            "Lead with clarity, not urgency.",
            "If everything is a priority, nothing is.",
            "Accountability needs speed and feedback.",
        ],
        "consulting": [
            "Most fixes fail at the handoff.",
            "Scope is a strategy, not paperwork.",
            "A good diagnosis beats a long deck.",
        ],
        "ai_in_business": [
            "AI is a capability, not a strategy.",
            "Start where process pain is already measured.",
            "The ROI gap is usually data + change management.",
        ],
        "productivity_leadership_strategy": [
            "Productivity is a leadership decision.",
            "Reduce meetings, not ambition.",
            "Strategy is constraint design.",
        ],
    }
    body = random.choice(themes[topic_key])
    templates = [
        f"{hook} {angle} isn't the problem.\n\nThe problem is decision latency. When leaders delay clarity, teams compensate with more meetings, more status updates, and slower execution.\n\nHere's the playbook I trust: write the decision in one sentence, define the success metric, and publish the trade-offs. Then review weekly with evidence, not opinions.\n\nWhat decision in your org would improve fastest if you made it today?",
        f"{hook} the hard part of {angle} is not expertise.\n\nIt's alignment. People agree on the outcome, then quietly disagree on the constraints: timelines, ownership, and what \"done\" actually means.\n\nTry this: run a 20-minute decision workshop. Finish with one owner, one metric, and one risk you'll actively monitor. You'll move faster without lowering standards.\n\nWhat would you change about how decisions are made in your team?",
        f"{hook} {angle} works differently than most teams expect.\n\nWhen we treat execution as a motivation issue, we end up adding pressure. When we treat it as a system issue, we remove friction: fewer handoffs, cleaner inputs, and tighter feedback loops.\n\nExample: we cut one approval step, tracked the cycle time, and set a clear review cadence. The result wasn't just faster work. It was fewer surprises.\n\nIf you could remove one bottleneck this week, what would it be?",
    ]
    hashtags = " ".join(cfg["hashtags"][:4])
    return _clean_post(random.choice(templates) + f"\n\n{hashtags}")


def generate_posts(topic_key: str, count: int) -> List[str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return [_fallback_generate(topic_key) for _ in range(count)]

    try:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
    except Exception:
        return [_fallback_generate(topic_key) for _ in range(count)]

    cfg = TOPICS[topic_key]
    angles = cfg["angles"]
    hashtags = cfg["hashtags"]
    chosen_angles = random.sample(angles, k=min(3, len(angles)))
    system = (
        "You write high-performing LinkedIn posts for leaders and operators. "
        "Use short sentences. Strong hook in first 2 lines. "
        "Storytelling or contrarian insight. No fluff. No emojis."
    )
    user = (
        f"Create {count} distinct LinkedIn post drafts about this topic category: {topic_key}.\n"
        f"Angles to cover across drafts: {', '.join(chosen_angles)}.\n"
        f"Requirements:\n"
        f"- 110-230 words each\n"
        f"- 3-6 short paragraphs\n"
        f"- First 2 lines must be the strongest hook\n"
        f"- Include one clear takeaway\n"
        f"- End with a single question CTA\n"
        f"- Include 3-6 hashtags at the end (from this list): {', '.join(hashtags)}\n"
        f"- Output format: for each draft, wrap with exactly:\n"
        f"===DRAFT n===\n"
        f"<post text>\n"
        f"(no extra commentary)\n"
        f"Ensure no duplicate drafts."
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.9")),
    )
    content = resp.choices[0].message.content or ""

    drafts: List[str] = []
    parts = re.split(r"^===DRAFT\s+(\d+)\s*===", content, flags=re.MULTILINE)
    # parts example: ["", "1", "draft1...\n", "2", "draft2...\n"]
    if len(parts) >= 3:
        for i in range(1, len(parts), 2):
            draft_text = parts[i + 1]
            draft_text = _clean_post(draft_text)
            if draft_text:
                drafts.append(draft_text)
    if len(drafts) < count:
        # Fallback: split by blank lines heuristics
        lines = [ln for ln in content.splitlines() if ln.strip()]
        # As a safe fallback, use fewer but at least unique
        while len(drafts) < count and lines:
            drafts.append(_fallback_generate(topic_key))
    return drafts[:count]


def pick_best_post(drafts: List[str], topic_key: str) -> Tuple[str, Dict[str, Any]]:
    scored = []
    for d in drafts:
        s = score_post(d, topic_key)
        scored.append((s["total"], d, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0]
    return best[1], best[2]


def suggest_post_time(now: Optional[datetime] = None) -> datetime:
    # Simple heuristic: next Tue/Wed/Thu at 10:30 local, else next business day at 10:30.
    if now is None:
        now = datetime.now().astimezone()

    local_tz = now.astimezone().tzinfo
    local = now
    # Candidate posting windows
    preferred_days = {1, 2, 3}  # Tue=1, Wed=2, Thu=3
    preferred_time = (10, 30)

    for day_offset in range(0, 14):
        cand = local + timedelta(days=day_offset)
        if cand.weekday() in preferred_days:
            cand = cand.replace(hour=preferred_time[0], minute=preferred_time[1], second=0, microsecond=0)
            if cand > local + timedelta(minutes=10):
                return cand

    # Fallback
    for day_offset in range(0, 14):
        cand = local + timedelta(days=day_offset)
        if cand.weekday() < 5:
            cand = cand.replace(hour=preferred_time[0], minute=preferred_time[1], second=0, microsecond=0)
            if cand > local + timedelta(minutes=10):
                return cand

    return local + timedelta(days=1)


def post_to_linkedin_api(text: str, scheduled_at: datetime, topic_key: str) -> requests.Response:
    endpoint = os.getenv("LINKEDIN_API_URL", "").strip()
    token = os.getenv("LINKEDIN_API_TOKEN", "").strip()
    if not endpoint or not token:
        raise RuntimeError("LinkedIn API not configured.")

    payload = {
        "text": text,
        "scheduled_at": scheduled_at.isoformat(),
        "topic": topic_key,
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    timeout_s = int(os.getenv("LINKEDIN_API_TIMEOUT_S", "30"))
    return requests.post(endpoint, headers=headers, json=payload, timeout=timeout_s)


def write_browser_fallback(text: str, scheduled_at: datetime, topic_key: str) -> str:
    out_dir = os.getenv("AUTOPOST_OUT_DIR", ".").strip() or "."
    os.makedirs(out_dir, exist_ok=True)
    ts = scheduled_at.strftime("%Y%m%d_%H%M")
    safe_topic = re.sub(r"[^a-zA-Z0-9_]+", "_", topic_key)
    out_path = os.path.join(out_dir, f"linkedin_post_{safe_topic}_{ts}.txt")
    content = (
        f"{text}\n\n"
        f"---\n"
        f"Suggested posting time (local): {scheduled_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return out_path


@dataclass
class PostJob:
    topic_key: str
    text: str
    scheduled_at: datetime
    selected_score: Dict[str, Any]


def schedule_jobs(jobs: List[PostJob]) -> None:
    if not jobs:
        return

    scheduler = BackgroundScheduler(timezone=tz_offset_local())
    for job in jobs:
        run_id = f"linkedin_autopost_{job.topic_key}_{int(job.scheduled_at.timestamp())}"

        def _do_post(job: PostJob = job) -> None:
            try:
                resp = post_to_linkedin_api(job.text, job.scheduled_at, job.topic_key)
                print(json.dumps({"status": "api_ok", "topic": job.topic_key, "http_status": resp.status_code}))
            except Exception as e:
                fallback_path = write_browser_fallback(job.text, job.scheduled_at, job.topic_key)
                print(
                    json.dumps(
                        {"status": "fallback_browser_copy_paste", "topic": job.topic_key, "path": fallback_path, "error": str(e)}
                    )
                )
                print("----- COPY/PASTE START -----")
                print(job.text)
                print("----- COPY/PASTE END -----")

        scheduler.add_job(
            _do_post,
            trigger=DateTrigger(run_date=job.scheduled_at),
            id=run_id,
            replace_existing=True,
        )

    scheduler.start()

    last_time = max(j.scheduled_at for j in jobs)
    while True:
        remaining = (last_time - datetime.now(tz=last_time.tzinfo)).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(remaining, 30))

    scheduler.shutdown(wait=False)


def tz_offset_local() -> timezone:
    # Convert local naive datetime to a timezone offset label for APScheduler.
    return datetime.now().astimezone().tzinfo or timezone.utc


def parse_topic_keys(arg: str) -> List[str]:
    if not arg or arg.strip().lower() == "all":
        return list(TOPICS.keys())
    keys = [k.strip() for k in arg.split(",") if k.strip()]
    normalized = []
    for k in keys:
        kk = k.lower()
        if kk in TOPICS:
            normalized.append(kk)
        else:
            # allow user-friendly aliases
            aliases = {
                "ai": "ai_in_business",
                "ai in business": "ai_in_business",
                "productivity": "productivity_leadership_strategy",
                "leadership": "productivity_leadership_strategy",
                "strategy": "productivity_leadership_strategy",
                "consulting": "consulting",
                "management": "management",
            }
            normalized.append(aliases.get(kk, kk))
    return [k for k in normalized if k in TOPICS]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", type=str, default="all", help="Comma-separated topic keys or 'all'.")
    parser.add_argument("--count", type=int, default=3, help="Drafts per topic.")
    parser.add_argument("--run", type=str, default="schedule", choices=["schedule", "now"], help="Schedule or run immediately.")
    parser.add_argument("--scheduled-at", type=str, default="", help="Optional ISO datetime. If empty, uses suggested time.")
    parser.add_argument("--keep-best-only", action="store_true", help="If multiple topics, keep only the best across them.")
    args = parser.parse_args()

    topics = parse_topic_keys(args.topic)
    if not topics:
        print(json.dumps({"error": "No valid topic keys provided."}))
        sys.exit(2)

    now = datetime.now().astimezone()
    scheduled_at = None
    if args.scheduled_at.strip():
        scheduled_at = datetime.fromisoformat(args.scheduled_at.strip())
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=now.astimezone().tzinfo)
    else:
        scheduled_at = suggest_post_time(now)

    jobs: List[PostJob] = []
    for topic_key in topics:
        drafts = generate_posts(topic_key, max(1, args.count))
        best_text, best_score = pick_best_post(drafts, topic_key)
        job_time = scheduled_at if args.run == "schedule" else datetime.now(tz=scheduled_at.tzinfo) + timedelta(seconds=5)
        jobs.append(PostJob(topic_key=topic_key, text=best_text, scheduled_at=job_time, selected_score=best_score))

    if len(jobs) > 1 and args.keep_best_only:
        jobs.sort(key=lambda j: j.selected_score.get("total", -1), reverse=True)
        jobs = [jobs[0]]

    # Auto-post Step 5: schedule + best post selection already done per topic; if multiple topics, schedule all unless keep_best_only.
    schedule_jobs(jobs)

    # Always print machine-readable summary
    summary = {
        "generated_topics": [j.topic_key for j in jobs],
        "scheduled_at": jobs[0].scheduled_at.isoformat() if jobs else None,
        "best_total_scores": [j.selected_score.get("total", None) for j in jobs],
    }
    print(json.dumps({"status": "done", "summary": summary}))


if __name__ == "__main__":
    main()

