#!/usr/bin/env python3
"""GeekNews RSS에서 관심 주제 글만 골라 digest/YYYY-MM-DD.md 로 요약한다.

- 피드의 제목/요약만 사용한다 (기사 본문 페이지는 열지 않음).
- 1차: 키워드로 후보를 거른다. 2차: `claude -p`가 관련성을 판단하고 자기 말로 요약한다.
- 결과는 이 스크립트가 있는 폴더의 digest/ 안에만 쓴다.
"""
import datetime
import html
import json
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

FEED_URL = "https://news.hada.io/rss/news"
TOPICS = ["AI 에이전트", "업무 자동화", "클로드(Claude)"]
KEYWORDS = [
    "에이전트", "agent", "agentic", "자동화", "automation", "automate", "워크플로",
    "workflow", "클로드", "claude", "anthropic", "앤트로픽", "mcp", "코파일럿", "copilot",
]
MAX_ITEMS = 5
MAX_CANDIDATES = 12
BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "digest"
ATOM = "{http://www.w3.org/2005/Atom}"


def fetch_feed(url):
    req = urllib.request.Request(url, headers={"User-Agent": "rss-digest/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # 리다이렉트 자동 추적
        return resp.read()


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def clean_link(link):
    return re.sub(r"[&?]utm_[^&]+", "", link or "")


def parse_feed(raw):
    root = ET.fromstring(raw)
    items = []
    for e in root.iter(ATOM + "entry"):  # Atom
        link = e.find(ATOM + "link")
        items.append({
            "title": clean(e.findtext(ATOM + "title")),
            "summary": clean(e.findtext(ATOM + "content") or e.findtext(ATOM + "summary")),
            "link": clean_link(link.get("href") if link is not None else ""),
        })
    for e in root.iter("item"):  # RSS 2.0
        items.append({
            "title": clean(e.findtext("title")),
            "summary": clean(e.findtext("description")),
            "link": clean_link(e.findtext("link")),
        })
    return items


def keyword_match(item):
    text = (item["title"] + " " + item["summary"]).lower()
    return any(k.lower() in text for k in KEYWORDS)


def load_existing(path):
    """이미 저장된 오늘 파일에서 기사(제목/요약/링크)를 읽어 온다."""
    if not path.exists():
        return []
    articles = []
    pattern = re.compile(r"^### (.+?)\n\n(.+?)\n\n원문: (\S+)", re.M | re.S)
    for m in pattern.finditer(path.read_text(encoding="utf-8")):
        articles.append({"title": m.group(1).strip(), "summary": m.group(2).strip(),
                         "link": m.group(3).strip()})
    return articles


def summarize_with_claude(candidates, existing):
    listing = "\n\n".join(
        f"[{i}] 제목: {c['title']}\n피드 요약: {c['summary'][:600]}"
        for i, c in enumerate(candidates)
    )
    saved = "\n".join(f"- {a['title']}: {a['summary']}" for a in existing) or "(없음)"
    prompt = f"""아래는 RSS 피드의 새 글 목록(제목과 피드 요약)이다. 이것만 근거로 판단하고 다른 자료는 찾지 마라.
관심 주제: {", ".join(TOPICS)}

1. 새 글 중 관심 주제와 실제로 관련 있는 글만 최대 {MAX_ITEMS}건 고른다 (키워드만 겹치고 주제와 무관하면 제외).
2. 고른 글마다 한국어 두 문장으로 요약한다. 원문 문장을 길게 그대로 옮기지 말고 자기 말로 다시 쓴다.
3. 오늘 이미 저장된 기사와 새로 고른 글을 모두 아우르는 "오늘의 세 줄 요약"을 한국어 세 줄로 쓴다.

오늘 이미 저장된 기사:
{saved}

JSON 하나만 출력하라 (코드펜스·설명 없이):
{{"overview": ["줄1", "줄2", "줄3"], "picks": [{{"index": 0, "summary": "두 문장 요약"}}]}}
새로 고를 글이 없으면 {{"overview": [], "picks": []}}

새 글 목록:
{listing}
"""
    proc = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text",
         "--disallowedTools", "WebFetch,WebSearch,Bash,Read,Write,Edit"],
        capture_output=True, text=True, timeout=300, cwd=str(BASE_DIR),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude 호출 실패: {proc.stderr.strip()}")
    match = re.search(r"\{.*\}", proc.stdout, re.S)
    if not match:
        raise RuntimeError(f"JSON 응답을 찾지 못함: {proc.stdout[:300]}")
    return json.loads(match.group(0))


def render(today, articles, overview):
    if not articles:
        return "해당 없음\n"
    lines = [f"# {today} 다이제스트", "", "## 오늘의 세 줄 요약", ""]
    lines += [f"- {s}" for s in overview[:3]]
    lines += ["", "## 기사", ""]
    for a in articles:
        lines += [f"### {a['title']}", "", a["summary"], "", f"원문: {a['link']}", ""]
    return "\n".join(lines)


def main():
    today = datetime.date.today().isoformat()
    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"{today}.md"
    existing = load_existing(out_path)
    seen = {a["link"] for a in existing}

    items = parse_feed(fetch_feed(FEED_URL))
    candidates = [i for i in items if keyword_match(i) and i["link"] not in seen][:MAX_CANDIDATES]
    result = summarize_with_claude(candidates, existing) if candidates else {"picks": []}
    picks = [p for p in result.get("picks", [])
             if isinstance(p.get("index"), int) and 0 <= p["index"] < len(candidates)][:MAX_ITEMS]
    new = [dict(candidates[p["index"]], summary=p["summary"].strip()) for p in picks]

    if new or not out_path.exists():  # 새 기사가 없으면 기존 파일은 그대로 둔다
        out_path.write_text(render(today, existing + new, result.get("overview", [])),
                            encoding="utf-8")
    print(f"저장: {out_path} · 새로 고른 기사 {len(new)}건 (누적 {len(existing) + len(new)}건)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        sys.exit(1)
