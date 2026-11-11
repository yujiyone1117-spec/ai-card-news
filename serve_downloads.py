#!/usr/bin/env python3
"""digest/ 폴더의 다이제스트를 카드뉴스로 보여 주고 파일을 내려받게 하는 로컬 서버.

    python3 serve_downloads.py [포트]   # 기본 8765, http://127.0.0.1:8765
    python3 serve_downloads.py build    # GitHub Pages용 정적 사이트를 docs/ 에 생성

- "/" 요청마다 digest/*.md 를 읽어 카드뉴스 페이지를 새로 만든다 (새 파일은 새로고침으로 반영).
- 날짜마다: 표지 카드 → 세 줄 요약 카드 → 기사 카드(제목·두 문장 요약·원문 링크).
- 파일은 /files/<이름> 으로 digest/ 안의 것만 다운로드로 내려준다.
- 127.0.0.1에만 바인딩해서 이 컴퓨터에서만 접속된다.
"""
import datetime
import html
import re
import sys
import urllib.parse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FILES_DIR = BASE_DIR / "digest"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8765
WEEKDAYS = "월화수목금토일"

CSS = """
:root {
  --blue-500:#3182F6; --blue-50:#E8F3FF; --white:#fff;
  --grey-900:#191F28; --grey-800:#333D4B; --grey-700:#4E5968; --grey-600:#6B7684;
  --grey-500:#8B95A1; --grey-400:#B0B8C1; --grey-300:#D1D6DB; --grey-200:#E5E8EB;
  --grey-100:#F2F4F6; --grey-50:#F9FAFB;
  --bg:var(--grey-100); --surface:var(--white); --text:var(--grey-900); --text-2:var(--grey-700);
  --text-3:var(--grey-500); --line:var(--grey-200); --chip-active-bg:var(--grey-900);
  --chip-active-fg:var(--white); --brand-weak:var(--blue-50); --brand:var(--blue-500);
  --press:rgba(0,0,0,.26);
  --shadow-1:0 1px 2px rgba(2,32,71,.04),0 1px 1px rgba(2,32,71,.04);
  --shadow-2:0 4px 12px rgba(2,32,71,.06),0 1px 2px rgba(2,32,71,.04);
  --ease:cubic-bezier(.22,.61,.36,1);
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --brand:#3485FA; --brand-weak:#202C4D;
    --bg:#17171C; --surface:#202027; --text:#FFFFFF; --text-2:#C3C3C6; --text-3:#9E9EA4;
    --line:#3C3C47; --chip-active-bg:#FFFFFF; --chip-active-fg:#17171C; --grey-100:#2C2C35;
    --shadow-1:none; --shadow-2:none; color-scheme: dark;
  }
}
* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body { margin:0; background:var(--bg); color:var(--text);
  font-family:"Pretendard Variable",Pretendard,-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;
  font-size:15px; line-height:1.5; letter-spacing:-.005em; }
main { max-width:560px; margin:0 auto; padding:32px 24px 64px; }
header h1 { font-size:28px; line-height:1.3; letter-spacing:-.02em; margin:0 0 4px; font-weight:700; }
header p { margin:0; color:var(--text-2); }
.chips { display:flex; gap:8px; overflow-x:auto; padding:20px 0 4px; scrollbar-width:none; }
.chips::-webkit-scrollbar { display:none; }
.chip { flex:none; height:34px; padding:0 14px; border-radius:999px; border:1px solid var(--line);
  background:var(--surface); color:var(--text); font:inherit; font-size:13px; font-weight:600;
  cursor:pointer; transition:background .2s var(--ease); font-variant-numeric:tabular-nums; }
.chip[aria-pressed="true"] { background:var(--chip-active-bg); color:var(--chip-active-fg); border-color:transparent; }
.deck[hidden] { display:none; }
.deck { margin-top:20px; }
.track { display:flex; gap:12px; overflow-x:auto; scroll-snap-type:x mandatory;
  scroll-behavior:smooth; padding:4px 24px 8px; margin:0 -24px; scrollbar-width:none; }
.track::-webkit-scrollbar { display:none; }
.card { flex:none; width:min(calc(100% - 24px), 480px, max(280px, 58vh)); aspect-ratio:4/5; scroll-snap-align:center;
  background:var(--surface); border-radius:24px; padding:28px 24px 24px; box-shadow:var(--shadow-2);
  display:flex; flex-direction:column; overflow:hidden; }
.eyebrow { font-size:13px; font-weight:600; color:var(--brand); margin:0 0 12px; font-variant-numeric:tabular-nums; }
.card h2 { font-size:22px; line-height:1.3; letter-spacing:-.015em; margin:0 0 16px; font-weight:700;
  overflow-wrap:anywhere; }
.card p.body { margin:0; font-size:17px; line-height:1.6; color:var(--text-2); overflow-wrap:anywhere;
  overflow:hidden; display:-webkit-box; -webkit-line-clamp:9; -webkit-box-orient:vertical; }
.spacer { flex:1; }
.cover { background:var(--brand-weak); box-shadow:none; }
.cover .date { font-size:15px; font-weight:600; color:var(--text-2); font-variant-numeric:tabular-nums; }
.cover h2 { font-size:40px; line-height:1.2; letter-spacing:-.02em; margin:12px 0 0; }
.cover .count { font-size:56px; font-weight:700; line-height:1; color:var(--brand); font-variant-numeric:tabular-nums; }
.cover .count-label { margin-top:8px; color:var(--text-2); }
.hint { font-size:13px; color:var(--text-3); margin-top:16px; }
ol.lines { margin:0; padding:0; list-style:none; display:flex; flex-direction:column; gap:16px; }
ol.lines li { display:flex; gap:12px; font-size:16px; line-height:1.55; color:var(--text-2); }
ol.lines .n { flex:none; width:24px; height:24px; border-radius:999px; background:var(--brand-weak);
  color:var(--brand); font-size:13px; font-weight:700; display:grid; place-items:center; margin-top:1px; }
a.source { align-self:flex-start; display:inline-flex; align-items:center; gap:4px; height:40px;
  padding:0 2px; color:var(--brand); font-weight:600; text-decoration:none; }
a.source:hover { text-decoration:underline; }
.empty-card h2 { color:var(--text-2); }
.controls { display:flex; align-items:center; justify-content:space-between; margin-top:16px; }
.counter { font-size:13px; font-weight:600; color:var(--text-3); font-variant-numeric:tabular-nums; }
.dots { display:flex; gap:6px; }
.dot { width:6px; height:6px; border-radius:999px; background:var(--grey-300); transition:width .2s var(--ease), background .2s var(--ease); }
.dot.on { width:18px; background:var(--text); }
.nav { display:flex; gap:8px; }
.icon-btn { width:40px; height:40px; border-radius:12px; border:1px solid var(--line); background:var(--surface);
  color:var(--text); display:grid; place-items:center; cursor:pointer; position:relative; }
.icon-btn:disabled { opacity:.3; cursor:default; }
.icon-btn svg { width:20px; height:20px; }
.download { margin-top:24px; display:flex; align-items:center; justify-content:center; gap:8px; width:100%; height:56px;
  border-radius:16px; background:var(--brand); color:#fff; font-size:17px; font-weight:700; text-decoration:none;
  position:relative; overflow:hidden; }
.download::after, .icon-btn::after { content:""; position:absolute; inset:0; background:var(--press);
  opacity:0; transition:opacity .12s var(--ease); border-radius:inherit; }
.download:active::after, .icon-btn:not(:disabled):active::after { opacity:1; }
.meta { margin-top:8px; text-align:center; font-size:13px; color:var(--text-3); font-variant-numeric:tabular-nums; }
.blank { margin-top:24px; background:var(--surface); border-radius:24px; padding:48px 24px; text-align:center; color:var(--text-2); }
:focus-visible { outline:1.5px solid var(--brand); outline-offset:2px; }
@media (prefers-reduced-motion: reduce) { .track { scroll-behavior:auto; } * { transition:none !important; } }
"""

JS = """
const decks = [...document.querySelectorAll('.deck')];
document.querySelectorAll('.chip').forEach(chip => chip.addEventListener('click', () => {
  document.querySelectorAll('.chip').forEach(c => c.setAttribute('aria-pressed', c === chip));
  decks.forEach(d => d.hidden = d.id !== chip.dataset.target);
}));
decks.forEach(deck => {
  const track = deck.querySelector('.track'), cards = [...track.children];
  const dots = [...deck.querySelectorAll('.dot')], counter = deck.querySelector('.counter');
  const prev = deck.querySelector('.prev'), next = deck.querySelector('.next');
  let idx = 0, settle;
  const render = () => {
    dots.forEach((d, i) => d.classList.toggle('on', i === idx));
    counter.textContent = (idx + 1) + ' / ' + cards.length;
    prev.disabled = idx === 0; next.disabled = idx === cards.length - 1;
  };
  const update = () => {  // 스크롤이 멈춘 뒤 화면 가운데 카드로 맞춘다
    const mid = track.scrollLeft + track.clientWidth / 2;
    idx = cards.reduce((best, c, i) =>
      Math.abs(c.offsetLeft + c.offsetWidth / 2 - mid) <
      Math.abs(cards[best].offsetLeft + cards[best].offsetWidth / 2 - mid) ? i : best, 0);
    render();
  };
  const go = i => {
    idx = Math.max(0, Math.min(cards.length - 1, i));
    render();
    track.scrollTo({left: cards[idx].offsetLeft - (track.clientWidth - cards[idx].offsetWidth) / 2,
                    behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  };
  prev.addEventListener('click', () => go(idx - 1));
  next.addEventListener('click', () => go(idx + 1));
  track.addEventListener('scroll', () => { clearTimeout(settle); settle = setTimeout(update, 120); }, {passive: true});
  track.addEventListener('keydown', e => {
    if (e.key === 'ArrowRight') { e.preventDefault(); go(idx + 1); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); go(idx - 1); }
  });
  update();
});
"""

ICON_PREV = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>'
ICON_NEXT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>'
ICON_DOWN = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>'


def esc(s):
    return html.escape(s or "", quote=True)


def parse_digest(path):
    text = path.read_text(encoding="utf-8")
    overview = []
    m = re.search(r"## 오늘의 세 줄 요약\s*\n(.*?)(?:\n## |\Z)", text, re.S)
    if m:
        overview = [l[2:].strip() for l in m.group(1).splitlines() if l.startswith("- ")]
    articles = [{"title": a.strip(), "summary": b.strip(), "link": c.strip()}
                for a, b, c in re.findall(r"^### (.+?)\n\n(.+?)\n\n원문: (\S+)", text, re.M | re.S)]
    return overview, articles


def date_label(stem):
    try:
        d = datetime.date.fromisoformat(stem)
    except ValueError:
        return stem, stem
    return f"{d.month}월 {d.day}일 {WEEKDAYS[d.weekday()]}요일", f"{d.month}.{d.day}"


def human_size(n):
    return f"{n:,}B" if n < 1024 else f"{n / 1024:.1f}KB"


def build_deck(f, active):
    overview, articles = parse_digest(f)
    long_label, _ = date_label(f.stem)
    cards = [f"""<article class="card cover">
  <div class="date">{esc(long_label)}</div>
  <h2>오늘의<br>AI 소식</h2>
  <div class="spacer"></div>
  <div class="count">{len(articles)}</div>
  <div class="count-label">AI 에이전트·업무 자동화·클로드 관련 기사</div>
  <div class="hint">{"옆으로 넘겨서 읽어 보세요" if articles else "오늘은 고른 기사가 없어요"}</div>
</article>"""]
    if overview:
        lines = "".join(f'<li><span class="n">{i}</span><span>{esc(s)}</span></li>'
                        for i, s in enumerate(overview[:3], 1))
        cards.append(f"""<article class="card">
  <p class="eyebrow">세 줄 요약</p>
  <h2>오늘 흐름을 한눈에 봐요</h2>
  <ol class="lines">{lines}</ol>
</article>""")
    for i, a in enumerate(articles, 1):
        link = a["link"] if a["link"].startswith(("http://", "https://")) else ""
        source = (f'<a class="source" href="{esc(link)}" target="_blank" rel="noopener noreferrer">'
                  f'원문 보기 {ICON_NEXT.replace("<svg ", "<svg width=16 height=16 ")}</a>') if link else ""
        cards.append(f"""<article class="card">
  <p class="eyebrow">기사 {i:02d} / {len(articles):02d}</p>
  <h2>{esc(a["title"])}</h2>
  <p class="body">{esc(a["summary"])}</p>
  <div class="spacer"></div>
  {source}
</article>""")
    if not articles:
        cards.append("""<article class="card empty-card">
  <p class="eyebrow">해당 없음</p>
  <h2>관심 주제에 맞는 기사가 없었어요</h2>
  <p class="body">다음 실행 때 새 기사가 생기면 여기에 쌓여요.</p>
</article>""")
    dots = "".join('<span class="dot"></span>' for _ in cards)
    st = f.stat()
    updated = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%H:%M")
    href = "files/" + urllib.parse.quote(f.name)  # 상대 경로라 GitHub Pages 하위 경로에서도 동작
    return f"""<section class="deck" id="d-{esc(f.stem)}" {"" if active else "hidden"} aria-label="{esc(long_label)} 카드뉴스">
  <div class="track" tabindex="0" aria-label="카드 목록, 좌우 화살표로 넘겨요">{"".join(cards)}</div>
  <div class="controls">
    <div class="dots" aria-hidden="true">{dots}</div>
    <div class="nav">
      <span class="counter" aria-live="polite"></span>
      <button class="icon-btn prev" aria-label="이전 카드">{ICON_PREV}</button>
      <button class="icon-btn next" aria-label="다음 카드">{ICON_NEXT}</button>
    </div>
  </div>
  <a class="download" href="{href}" download>{ICON_DOWN}파일 받기</a>
  <div class="meta">{esc(f.name)} · {human_size(st.st_size)} · {updated} 업데이트</div>
</section>"""


def build_page():
    files = sorted((f for f in FILES_DIR.glob("*.md") if f.is_file()), key=lambda f: f.name, reverse=True)
    if files:
        chips = "".join(
            f'<button class="chip" data-target="d-{esc(f.stem)}" aria-pressed="{"true" if i == 0 else "false"}">'
            f'{esc(date_label(f.stem)[1])}</button>' for i, f in enumerate(files))
        body = f'<nav class="chips" aria-label="날짜 선택">{chips}</nav>' + "".join(
            build_deck(f, i == 0) for i, f in enumerate(files))
    else:
        body = '<div class="blank">아직 다이제스트가 없어요. rss_digest.py를 실행하면 여기에 쌓여요.</div>'
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>AI 소식 카드뉴스</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>{CSS}</style></head>
<body><main>
<header><h1>AI 소식 카드뉴스</h1><p>매일 고른 기사를 카드로 넘겨 보고, 파일로 받을 수 있어요.</p></header>
{body}
</main><script>{JS}</script></body></html>
""".encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            data = build_page()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        elif path.startswith("/files/") and "/" not in path[len("/files/"):]:
            name = path[len("/files/"):]
            self.download_name = urllib.parse.unquote(name)
            self.path = "/" + name  # digest/ 기준 경로로 바꿔 기본 핸들러에 맡김
            super().do_GET()
        else:
            self.send_error(404)

    def list_directory(self, path):  # 폴더 목록 자동 노출 막기
        self.send_error(404)

    def end_headers(self):
        name = getattr(self, "download_name", None)
        if name:
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
        super().end_headers()

    def guess_type(self, path):
        if str(path).endswith(".md"):
            return "text/markdown; charset=utf-8"
        return super().guess_type(path)


def build_static(out_dir):
    """GitHub Pages용 정적 사이트를 만든다: index.html + files/*.md + .nojekyll"""
    out_dir = Path(out_dir).resolve()
    files_out = out_dir / "files"
    files_out.mkdir(parents=True, exist_ok=True)
    for old in files_out.glob("*.md"):  # digest/ 에서 사라진 파일은 사이트에서도 뺀다
        if not (FILES_DIR / old.name).exists():
            old.unlink()
    for f in FILES_DIR.glob("*.md"):
        (files_out / f.name).write_bytes(f.read_bytes())
    (out_dir / "index.html").write_bytes(build_page())
    (out_dir / ".nojekyll").write_text("")  # Jekyll이 .md를 HTML로 바꾸지 않게
    print(f"정적 사이트 생성: {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_static(sys.argv[2] if len(sys.argv) > 2 else BASE_DIR / "docs")
        sys.exit(0)
    FILES_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=str(FILES_DIR)))
    print(f"서빙 중: http://127.0.0.1:{PORT}  (폴더: {FILES_DIR}) · 종료: Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
