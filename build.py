"""
실시간 급상승 검색어 정적 사이트 생성기 (Python 표준 라이브러리만 사용)

하는 일
  1) 구글 트렌드 급상승 검색어 RSS를 받아 순위·변동을 계산하고 data/ 폴더에 기록을 쌓습니다.
  2) 쌓인 기록으로 site/ 폴더에 HTML을 만듭니다.
     - index.html        : 지금의 실시간 순위
     - k/<검색어>.html    : 검색어별 페이지 (언제 떴는지, 최고 순위, 순위 변화, 관련 뉴스)
     - d/<날짜>.html      : 날짜별 기록
     - about / privacy / contact, sitemap.xml, robots.txt, ads.txt

실행
  py build.py              # 새 데이터 받아서 사이트 생성
  py build.py --no-fetch   # 데이터 안 받고 지금 기록으로 사이트만 다시 생성
미리보기
  py -m http.server 8000 -d site   → http://localhost:8000
"""

import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
SITE = os.path.join(BASE, "site")
STATIC = os.path.join(BASE, "static")
KST = timezone(timedelta(hours=9))
NS = {"ht": "https://trends.google.com/trending/rss"}
HISTORY_LIMIT = 300   # 검색어 하나당 순위 기록 최대 개수
NEWS_LIMIT = 12       # 검색어 하나당 보관할 관련 뉴스 수


# ───────────────────────── 공통 도구 ─────────────────────────

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def kst(ts):
    return datetime.fromtimestamp(ts, KST)


def fmt_long(ts):
    d = kst(ts)
    return f"{d.year}년 {d.month}월 {d.day}일 {d.hour}시 {d.minute}분"


def fmt_hm(ts):
    return kst(ts).strftime("%H:%M")


def fmt_stamp(ts):
    return kst(ts).strftime("%Y.%m.%d %H:%M") + " 기준"


def day_of(ts):
    return kst(ts).strftime("%Y-%m-%d")


def day_label(day):
    y, m, d = day.split("-")
    wd = "월화수목금토일"[datetime(int(y), int(m), int(d)).weekday()]
    return f"{int(y)}년 {int(m)}월 {int(d)}일 ({wd})"


def fmt_traffic(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M+"
    if n >= 10_000:
        return f"{n / 10_000:g}만+"
    if n >= 1_000:
        return f"{n / 1_000:g}천+"
    return f"{n}+"


def traffic_words(n):
    """문장용 검색량: 200 → '200회', 2000 → '2천 회', 20000 → '2만 회'"""
    if n >= 10_000:
        return f"{n / 10_000:g}만 회"
    if n >= 1_000:
        return f"{n / 1_000:g}천 회"
    return f"{n}회"


def duration(sec):
    m = round(sec / 60)
    if m < 60:
        return f"{max(m, 1)}분"
    h = m // 60
    if h < 24:
        return f"약 {h}시간"
    return f"약 {h // 24}일"


def josa(word, with_final, without_final):
    """한국어 조사: 받침 있으면 앞의 것(은/이), 없으면 뒤의 것(는/가). 한글이 아니면 둘 다 표기."""
    c = word.strip()[-1:] if word.strip() else ""
    if "가" <= c <= "힣":
        return with_final if (ord(c) - 0xAC00) % 28 else without_final
    return f"{with_final}({without_final})"


def parse_traffic(text):
    if not text:
        return 0
    t = text.replace(",", "").replace("+", "").strip()
    m = re.match(r"([\d.]+)\s*([KkMm만천]?)", t)
    if not m:
        return 0
    mult = {"K": 1e3, "k": 1e3, "M": 1e6, "m": 1e6, "만": 1e4, "천": 1e3}.get(m.group(2), 1)
    return int(float(m.group(1)) * mult)


# ───────────────────────── 외국어 검색어 거르기 ─────────────────────────
# 구글의 한국 목록에도 'cuaca besok'(인도네시아어), 'sxmb'(베트남 복권) 같은 외국어 검색어가 섞여 들어온다.
# 규칙: 검색어에 한글이 있으면 통과 → 관련 기사 제목에 한글이 있으면 통과
#       → 기사 제목이 영어면 통과(ps5, twitch 같은 세계적 화제) → 그 밖의 언어 기사뿐이면 제외.

HANGUL = re.compile(r"[가-힣]")
ENGLISH_WORDS = {
    "the", "a", "an", "of", "and", "to", "in", "is", "are", "for", "with", "on", "at", "after", "as",
    "by", "from", "new", "how", "what", "why", "who", "will", "its", "it", "be", "has", "have", "was",
    "this", "that", "you", "your", "out", "up", "over", "about", "into", "more", "than", "after", "before",
}


def looks_english(text):
    if re.search(r"[^\x00-\x7F‘’“”–—…]", text):   # 악센트·다른 문자가 있으면 영어가 아님 (베트남어 등)
        return False
    words = re.findall(r"[a-z']+", text.lower())
    return sum(w in ENGLISH_WORDS for w in words) >= 2 or (len(words) >= 3 and sum(w in ENGLISH_WORDS for w in words) >= 1)


def is_relevant(keyword, news):
    if HANGUL.search(keyword):
        return True
    titles = [n.get("title", "") for n in news if n.get("title")]
    if not titles:
        return bool(re.fullmatch(r"[\x00-\x7F]+", keyword))   # 기사 없는 영문·숫자 검색어는 일단 통과
    if any(HANGUL.search(t) for t in titles):
        return True
    return sum(looks_english(t) for t in titles) * 2 >= len(titles)   # 절반 이상이 영어 기사


# ───────────────────────── 설정 ─────────────────────────

def load_config():
    cfg = {
        "siteName": "실검",
        "siteDescription": "구글 트렌드 데이터로 보는 실시간 급상승 검색어 순위와 검색어별 기록",
        "siteUrl": "",
        "geo": "KR",
        "adsenseClient": "",
        "contactEmail": "",
        "privacyEffectiveDate": "",
    }
    cfg.update(load_json(os.path.join(BASE, "config.json"), {}))
    if os.environ.get("SITE_URL"):          # GitHub Actions가 넘겨주는 주소가 우선
        cfg["siteUrl"] = os.environ["SITE_URL"]
    if cfg["siteUrl"] and not cfg["siteUrl"].endswith("/"):
        cfg["siteUrl"] += "/"
    return cfg


# ───────────────────────── 1단계: 데이터 수집 ─────────────────────────

def fetch_items(geo):
    url = f"https://trends.google.com/trending/rss?geo={geo}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (trending-keywords static site)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        root = ET.fromstring(r.read())
    items = []
    for idx, it in enumerate(root.iter("item")):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        traffic_text = it.findtext("ht:approx_traffic", default="", namespaces=NS)
        try:
            started = parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
        except (TypeError, ValueError):
            started = 0
        news = [{
            "title": (n.findtext("ht:news_item_title", default="", namespaces=NS) or "").strip(),
            "url": (n.findtext("ht:news_item_url", default="", namespaces=NS) or "").strip(),
            "source": (n.findtext("ht:news_item_source", default="", namespaces=NS) or "").strip(),
        } for n in it.findall("ht:news_item", NS)]
        items.append({
            "keyword": title,
            "traffic": parse_traffic(traffic_text),
            "startedAt": started,
            "news": [n for n in news if n["url"].startswith("http")],
            "_order": idx,
        })
    dropped = [x["keyword"] for x in items if not is_relevant(x["keyword"], x["news"])]
    if dropped:
        print("외국어 검색어 제외:", ", ".join(dropped))
    items = [x for x in items if x["keyword"] not in dropped]
    # 검색량 많은 순 → 최근에 뜬 순 → 구글 원래 순서
    items.sort(key=lambda x: (-x["traffic"], -x["startedAt"], x["_order"]))
    for i, x in enumerate(items, 1):
        x["rank"] = i
        del x["_order"]
    return items


def make_slug(keyword, slugs):
    if keyword in slugs:
        return slugs[keyword]
    s = re.sub(r"[^\w]+", "-", keyword.lower(), flags=re.UNICODE).strip("-_")[:60]
    h = hashlib.md5(keyword.encode("utf-8")).hexdigest()[:6]
    if not s:
        s = "k-" + h
    if s in set(slugs.values()):     # 'GTA 6'와 'gta-6'처럼 겹치면 구분값 추가
        s = f"{s}-{h}"
    slugs[keyword] = s
    return s


def update_data(cfg):
    now = time.time()
    items = fetch_items(cfg["geo"])
    if not items:
        raise RuntimeError("구글 트렌드에서 검색어를 하나도 받지 못했습니다.")

    # 순위 변동 계산 (순위가 실제로 바뀐 순간의 직전 순위와 비교)
    state = load_json(os.path.join(DATA, "state.json"), {"ranks": {}, "prevRanks": {}, "changedAt": 0})
    current = {x["keyword"]: x["rank"] for x in items}
    if current != state["ranks"]:
        state["prevRanks"], state["ranks"], state["changedAt"] = state["ranks"], current, now
    prev = state["prevRanks"]
    for x in items:
        old = prev.get(x["keyword"])
        if not prev:
            x["change"], x["diff"] = "same", 0
        elif old is None:
            x["change"], x["diff"] = "new", 0
        elif old != x["rank"]:
            x["change"], x["diff"] = ("up" if old > x["rank"] else "down"), abs(old - x["rank"])
        else:
            x["change"], x["diff"] = "same", 0

    slugs = load_json(os.path.join(DATA, "slugs.json"), {})
    for x in items:
        x["slug"] = make_slug(x["keyword"], slugs)
    today = day_of(now)
    snapshot_slugs = [x["slug"] for x in items]

    # 검색어별 기록
    for x in items:
        path = os.path.join(DATA, "keywords", x["slug"] + ".json")
        # 처음 등장 시각은 구글이 기록한 급상승 시작 시각(없으면 지금)
        started = x["startedAt"] if 0 < x["startedAt"] <= now else now
        k = load_json(path, None) or {
            "keyword": x["keyword"], "slug": x["slug"], "firstSeen": started, "lastSeen": now,
            "peakRank": x["rank"], "peakTraffic": 0, "history": [], "news": [], "days": [], "related": [],
        }
        k["lastSeen"] = now
        k["peakRank"] = min(k["peakRank"], x["rank"])
        k["peakTraffic"] = max(k["peakTraffic"], x["traffic"])
        if not k["history"] or k["history"][-1][1] != x["rank"] or k["history"][-1][2] != x["traffic"]:
            k["history"].append([round(now), x["rank"], x["traffic"]])
            k["history"] = k["history"][-HISTORY_LIMIT:]
        known = {n["url"] for n in k["news"]}
        k["news"] = ([n for n in x["news"] if n["url"] not in known] + k["news"])[:NEWS_LIMIT]
        if today not in k["days"]:
            k["days"].append(today)
        k["related"] = ([s for s in snapshot_slugs if s != x["slug"] and s not in k["related"]] + k["related"])[:20]
        save_json(path, k)

    # 날짜별 기록
    dpath = os.path.join(DATA, "days", today + ".json")
    day = load_json(dpath, {"date": today, "keywords": {}})
    for x in items:
        started = x["startedAt"] if 0 < x["startedAt"] <= now and day_of(x["startedAt"]) == today else now
        d = day["keywords"].setdefault(x["keyword"], {
            "slug": x["slug"], "firstSeen": started, "peakRank": x["rank"], "peakTraffic": x["traffic"]})
        d["peakRank"] = min(d["peakRank"], x["rank"])
        d["peakTraffic"] = max(d["peakTraffic"], x["traffic"])
        d["lastSeen"] = now
    save_json(dpath, day)

    save_json(os.path.join(DATA, "slugs.json"), slugs)
    save_json(os.path.join(DATA, "state.json"), state)
    save_json(os.path.join(DATA, "latest.json"), {"generatedAt": round(now), "geo": cfg["geo"], "items": [
        {k: x[k] for k in ("rank", "keyword", "slug", "traffic", "startedAt", "change", "diff")}
        | {"news": x["news"][:3]} for x in items]})
    print(f"수집 완료: {len(items)}개 검색어 ({fmt_stamp(now)})")


# ───────────────────────── 2단계: 페이지 생성 ─────────────────────────

def layout(cfg, *, title, body, root, path, desc="", body_attr=""):
    canonical = f'<link rel="canonical" href="{e(cfg["siteUrl"] + path)}">' if cfg["siteUrl"] else ""
    ads = ""
    if cfg["adsenseClient"]:
        ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
               f'?client={e(cfg["adsenseClient"])}" crossorigin="anonymous"></script>')
    desc = desc or cfg["siteDescription"]
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc[:160])}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc[:160])}">
<meta property="og:type" content="website">
{canonical}
<link rel="stylesheet" href="{root}style.css">
{ads}
</head>
<body{body_attr}>
<header>
  <div class="top">
    <a class="logo" href="{root}">{e(cfg["siteName"])}<span>.</span></a>
    <nav>
      <a href="{root}">실시간 순위</a>
      <a href="{root}d/">날짜별 기록</a>
      <a href="{root}about.html">소개</a>
    </nav>
  </div>
</header>
<main>
{body}
</main>
<footer>
  <nav><a href="{root}about.html">사이트 소개</a> · <a href="{root}privacy.html">개인정보처리방침</a> · <a href="{root}contact.html">문의</a></nav>
  <p>데이터 출처: Google 트렌드 '급상승 검색어'. 검색량은 구글이 제공하는 대략치이며, 이 사이트는 Google과 관련이 없습니다.</p>
</footer>
<script src="{root}app.js"></script>
</body>
</html>
"""


def chg_html(change, diff):
    if change == "new":
        return '<span class="chg new">NEW</span>'
    if change == "up":
        return f'<span class="chg up">▲ {diff}</span>'
    if change == "down":
        return f'<span class="chg down">▼ {diff}</span>'
    return '<span class="chg same">–</span>'


def search_links(kw):
    q = quote(kw)
    return (f'<a class="pill" href="https://www.google.com/search?q={q}" target="_blank" rel="noopener nofollow">구글에서 검색</a>'
            f'<a class="pill" href="https://search.naver.com/search.naver?query={q}" target="_blank" rel="noopener nofollow">네이버에서 검색</a>')


def render_index(cfg, latest, days):
    items = latest["items"]
    root = "./"
    top = items[:10]
    roll = "".join(
        f'<li><span class="n">{x["rank"]}</span><span class="k">{e(x["keyword"])}</span>{chg_html(x["change"], x["diff"])}</li>'
        for x in top + top[:1])
    drop = "".join(
        f'<a href="k/{e(x["slug"])}.html"><span class="n">{x["rank"]}</span><span class="k">{e(x["keyword"])}</span>{chg_html(x["change"], x["diff"])}</a>'
        for x in top)

    def row(x):
        headline = f'<span class="sub">{e(x["news"][0]["title"])}</span>' if x["news"] else ""
        return (f'<li class="row"><a class="row-main" href="k/{e(x["slug"])}.html">'
                f'<span class="rank{" hot" if x["rank"] <= 3 else ""}">{x["rank"]}</span>'
                f'<span class="kw-wrap"><span class="kw">{e(x["keyword"])}</span>{headline}</span>'
                f'<span class="traffic">{fmt_traffic(x["traffic"])}</span>{chg_html(x["change"], x["diff"])}</a></li>')

    half = (len(items) + 1) // 2
    cols = f'<ul class="col">{"".join(map(row, items[:half]))}</ul><ul class="col">{"".join(map(row, items[half:]))}</ul>'

    today = days[0] if days else None
    today_html = ""
    if today:
        kws = sorted(today["keywords"].items(), key=lambda kv: -kv[1]["firstSeen"])
        rows = "".join(
            f'<li><span class="time">{fmt_hm(v["firstSeen"])}</span><a href="k/{e(v["slug"])}.html">{e(k)}</a>'
            f'<span class="muted">최고 {v["peakRank"]}위</span></li>' for k, v in kws[:30])
        today_html = f"""
<section class="card">
  <div class="card-head"><h2>{e(day_label(today["date"]))} 급상승했던 검색어 <small>{len(kws)}개</small></h2>
  <a class="more" href="d/{today["date"]}.html">전체 보기 →</a></div>
  <ul class="timeline">{rows}</ul>
</section>"""
    recent = "".join(f'<a class="pill" href="d/{d["date"]}.html">{e(day_label(d["date"]))}</a>' for d in days[1:8])
    recent_html = f'<section class="card pad"><h2>지난 기록</h2><div class="pills">{recent}</div></section>' if recent else ""

    body = f"""
<div class="ticker-wrap" id="tickerWrap">
  <div class="ticker" id="ticker"><span class="label">급상승</span>
    <div class="roll"><ul id="rollList">{roll}</ul></div><span class="muted">▼</span></div>
  <div class="dropdown">{drop}</div>
</div>
<section class="card">
  <div class="card-head"><h1><span class="accent">실시간</span> 급상승 검색어</h1>
  <span class="muted">{fmt_stamp(latest["generatedAt"])}</span></div>
  <div class="list">{cols}</div>
</section>
{today_html}
{recent_html}
"""
    desc = "지금 뜨는 검색어: " + ", ".join(x["keyword"] for x in items[:10])
    return layout(cfg, title=f'{cfg["siteName"]} - 실시간 급상승 검색어 순위', body=body, root=root, path="",
                  desc=desc, body_attr=f' data-generated="{latest["generatedAt"]}"')


def render_keyword(cfg, k, current_ranks, names_by_slug):
    root = "../"
    kw = k["keyword"]
    news = k["news"]
    sources = []
    for n in news:
        if n["source"] and n["source"] not in sources:
            sources.append(n["source"])

    # 데이터로 문장 만들기 (AI 없이)
    p = [f"'{e(kw)}'{josa(kw, '은', '는')} {fmt_long(k['firstSeen'])}에 구글 트렌드 한국 급상승 검색어 목록에 처음 올랐습니다."]
    p.append(f"지금까지 확인된 최고 순위는 <b>{k['peakRank']}위</b>이고, 구글이 집계한 검색량은 "
             f"<b>{traffic_words(k['peakTraffic'])} 이상</b>입니다.")
    span = k["lastSeen"] - k["firstSeen"]
    if span >= 60:
        p.append(f"마지막으로 순위권에서 확인된 시각은 {fmt_long(k['lastSeen'])}로, 처음 등장한 뒤 {duration(span)} 동안 목록에 머물렀습니다.")
    if len(k["days"]) > 1:
        p.append(f"이 검색어는 지금까지 모두 {len(k['days'])}일 동안 급상승 검색어에 올랐습니다.")
    if news:
        src = ", ".join(sources[:4]) + (" 등" if len(sources) > 4 else "")
        p.append(f"관련 보도는 {e(src)}에서 나왔고, 대표 기사 제목은 '{e(news[0]['title'])}'입니다.")

    now_rank = current_ranks.get(kw)
    badge = (f'<span class="badge live">현재 {now_rank}위</span>' if now_rank
             else '<span class="badge">현재 순위권 밖</span>')

    hist_rows = "".join(
        f'<tr><td>{kst(ts).strftime("%m.%d %H:%M")}</td><td>{rank}위</td><td>{fmt_traffic(tr)}</td></tr>'
        for ts, rank, tr in reversed(k["history"][-30:]))
    news_html = "".join(
        f'<li><a href="{e(n["url"])}" target="_blank" rel="noopener nofollow"><b>{e(n["source"])}</b>{e(n["title"])}</a></li>'
        for n in news) or '<li class="muted">수집된 관련 뉴스가 없습니다.</li>'
    related = "".join(f'<a class="pill" href="{e(s)}.html">{e(names_by_slug[s])}</a>'
                      for s in k["related"] if s in names_by_slug)
    days_html = "".join(f'<a class="pill" href="../d/{d}.html">{e(day_label(d))}</a>' for d in reversed(k["days"]))

    body = f"""
<article class="card pad">
  <p class="crumb"><a href="../">실시간 순위</a> › <a href="../d/{k['days'][-1]}.html">{e(day_label(k['days'][-1]))}</a></p>
  <h1 class="kw-title">{e(kw)} {badge}</h1>
  <dl class="stats">
    <div><dt>최고 순위</dt><dd>{k['peakRank']}위</dd></div>
    <div><dt>검색량</dt><dd>{fmt_traffic(k['peakTraffic'])}</dd></div>
    <div><dt>처음 등장</dt><dd>{kst(k['firstSeen']).strftime('%m.%d %H:%M')}</dd></div>
    <div><dt>관련 기사</dt><dd>{len(news)}건</dd></div>
  </dl>
  <div class="prose">{"".join(f"<p>{x}</p>" for x in p)}</div>
  <div class="pills">{search_links(kw)}</div>
</article>
<section class="card pad"><h2>관련 뉴스</h2><ul class="news">{news_html}</ul></section>
<section class="card pad"><h2>순위 변화 기록</h2>
  <table class="tbl"><thead><tr><th>시각</th><th>순위</th><th>검색량</th></tr></thead><tbody>{hist_rows}</tbody></table>
</section>
{f'<section class="card pad"><h2>같은 시간에 뜬 검색어</h2><div class="pills">{related}</div></section>' if related else ''}
<section class="card pad"><h2>급상승한 날</h2><div class="pills">{days_html}</div></section>
"""
    title = f"{kw} 급상승 이유와 관련 뉴스 ({kst(k['firstSeen']).month}월 {kst(k['firstSeen']).day}일) - {cfg['siteName']}"
    desc = f"'{kw}' 실시간 급상승 검색어 기록: 최고 {k['peakRank']}위, 검색량 {fmt_traffic(k['peakTraffic'])}. " + \
           (news[0]["title"] if news else "")
    return layout(cfg, title=title, body=body, root=root, path=f"k/{quote(k['slug'])}.html", desc=desc)


def render_day(cfg, day, prev_day, next_day):
    rows = "".join(
        f'<tr><td>{fmt_hm(v["firstSeen"])}</td><td class="left"><a href="../k/{e(v["slug"])}.html">{e(k)}</a></td>'
        f'<td>{v["peakRank"]}위</td><td>{fmt_traffic(v["peakTraffic"])}</td></tr>'
        for k, v in sorted(day["keywords"].items(), key=lambda kv: -kv[1]["firstSeen"]))
    top = sorted(day["keywords"].items(), key=lambda kv: (kv[1]["peakRank"], -kv[1]["peakTraffic"]))[:5]
    nav = (f'<a href="{prev_day}.html">← {e(day_label(prev_day))}</a>' if prev_day else "<span></span>") + \
          (f'<a href="{next_day}.html">{e(day_label(next_day))} →</a>' if next_day else "<span></span>")
    label = day_label(day["date"])
    summary = (f"{label}에는 모두 {len(day['keywords'])}개의 검색어가 구글 트렌드 한국 급상승 목록에 올랐습니다. "
               f"가장 높이 오른 검색어는 " + ", ".join(f"'{e(k)}'" for k, _ in top[:3]) + "입니다.") if top else ""
    body = f"""
<section class="card pad">
  <p class="crumb"><a href="./">날짜별 기록</a></p>
  <h1>{e(label)} 실시간 급상승 검색어</h1>
  <p class="prose">{summary}</p>
  <table class="tbl"><thead><tr><th>등장</th><th class="left">검색어</th><th>최고 순위</th><th>검색량</th></tr></thead>
  <tbody>{rows}</tbody></table>
  <div class="daynav">{nav}</div>
</section>"""
    return layout(cfg, title=f"{label} 실시간 급상승 검색어 기록 - {cfg['siteName']}", body=body, root="../",
                  path=f"d/{day['date']}.html", desc=f"{label} 급상승 검색어: " + ", ".join(k for k, _ in top))


def render_days_index(cfg, days):
    rows = "".join(f'<li><a href="{d["date"]}.html">{e(day_label(d["date"]))}</a><span class="muted">{len(d["keywords"])}개</span></li>'
                   for d in days)
    body = f'<section class="card pad"><h1>날짜별 급상승 검색어 기록</h1><ul class="daylist">{rows or "<li>아직 기록이 없습니다.</li>"}</ul></section>'
    return layout(cfg, title=f"날짜별 기록 - {cfg['siteName']}", body=body, root="../", path="d/")


def render_static_pages(cfg):
    name = cfg["siteName"]
    email = cfg["contactEmail"]
    contact_line = (f'<a href="mailto:{e(email)}">{e(email)}</a>' if email else "(config.json에 contactEmail을 입력하세요)")
    effective = cfg["privacyEffectiveDate"] or day_of(time.time())
    pages = {
        "about.html": ("사이트 소개", f"""
<h1>{e(name)} 소개</h1>
<p>{e(name)}{josa(name, '은', '는')} 지금 사람들이 많이 찾는 검색어를 한눈에 보여주는 사이트입니다. 구글 트렌드가 공개하는 한국 '급상승 검색어' 데이터를
20분 안팎 간격으로 받아 순위를 매기고, 검색어마다 언제 처음 떴는지, 어디까지 올랐는지, 어떤 뉴스와 함께 떴는지를 기록합니다.</p>
<h2>순위는 이렇게 매깁니다</h2>
<ul><li>구글이 집계한 대략 검색량(예: 500+, 2천+)이 많은 순서로 정렬합니다.</li>
<li>검색량이 같으면 더 최근에 급상승한 검색어를 위에 둡니다.</li>
<li>▲▼ 표시는 순위가 바뀌기 직전과 비교한 변동이고, NEW는 직전 순위에 없던 검색어입니다.</li></ul>
<h2>알아두실 점</h2>
<ul><li>검색량은 구글이 제공하는 대략치라서 정확한 검색 횟수가 아닙니다.</li>
<li>관련 뉴스는 구글 트렌드가 연결한 기사이며, 기사 내용의 저작권은 각 언론사에 있습니다.</li>
<li>이 사이트는 Google, 네이버 등 검색 서비스와 관련이 없는 개인 운영 사이트입니다.</li></ul>
"""),
        "privacy.html": ("개인정보처리방침", f"""
<h1>개인정보처리방침</h1>
<p>{e(name)}(이하 '사이트')는 회원가입이나 로그인 기능이 없으며, 방문자의 이름·연락처 같은 개인정보를 직접 수집하지 않습니다.</p>
<h2>1. 자동으로 수집될 수 있는 정보</h2>
<p>사이트를 호스팅하는 서비스(GitHub Pages)는 보안과 운영을 위해 접속 IP 주소, 브라우저 종류, 접속 시각 같은 기록을 남길 수 있습니다.
이 정보는 호스팅 업체의 정책에 따라 처리됩니다.</p>
<h2>2. 광고와 쿠키</h2>
<p>사이트는 Google 애드센스 등 제3자 광고 서비스를 이용할 수 있습니다. Google을 포함한 제3자 업체는 쿠키를 사용해 방문자가 이 사이트나
다른 사이트를 방문한 기록을 바탕으로 광고를 보여줄 수 있습니다.</p>
<ul><li>Google이 광고 쿠키를 사용하는 방식: <a href="https://policies.google.com/technologies/ads?hl=ko" target="_blank" rel="noopener">Google 광고 정책</a></li>
<li>맞춤 광고를 원하지 않으면 <a href="https://adssettings.google.com" target="_blank" rel="noopener">Google 광고 설정</a>에서 끌 수 있습니다.</li>
<li>브라우저 설정에서 쿠키 저장을 거부할 수도 있습니다. 이 경우에도 사이트 이용에는 문제가 없습니다.</li></ul>
<h2>3. 문의</h2>
<p>개인정보와 관련된 문의는 {contact_line}로 보내 주세요.</p>
<p class="muted">시행일: {e(effective)}</p>
"""),
        "contact.html": ("문의", f"""
<h1>문의</h1>
<p>사이트 이용, 잘못된 정보 신고, 삭제 요청, 광고·제휴 문의는 아래 이메일로 보내 주세요.</p>
<p class="big">{contact_line}</p>
<p class="muted">검색어 순위는 구글 트렌드 데이터를 자동으로 반영한 것이라 특정 검색어를 임의로 넣거나 빼지 않습니다.</p>
"""),
    }
    for fname, (title, content) in pages.items():
        write(os.path.join(SITE, fname), layout(cfg, title=f"{title} - {name}", root="./", path=fname,
                                                body=f'<article class="card pad prose">{content}</article>'))


def build_site(cfg):
    latest = load_json(os.path.join(DATA, "latest.json"), None)
    if not latest:
        sys.exit("data/latest.json이 없습니다. 먼저 --no-fetch 없이 실행해 데이터를 받아 주세요.")

    if os.path.isdir(SITE):
        shutil.rmtree(SITE)
    os.makedirs(SITE)
    for f in os.listdir(STATIC):
        shutil.copy(os.path.join(STATIC, f), SITE)
    shutil.copy(os.path.join(DATA, "latest.json"), SITE)

    days_dir = os.path.join(DATA, "days")
    day_files = sorted((f[:-5] for f in os.listdir(days_dir) if f.endswith(".json")), reverse=True) \
        if os.path.isdir(days_dir) else []
    days = [load_json(os.path.join(days_dir, d + ".json"), None) for d in day_files]
    days = [d for d in days if d]

    kw_dir = os.path.join(DATA, "keywords")
    keywords = [load_json(os.path.join(kw_dir, f), None) for f in os.listdir(kw_dir) if f.endswith(".json")] \
        if os.path.isdir(kw_dir) else []
    # 예전에 쌓인 외국어 검색어도 페이지·목록에서 뺀다 (기록 파일은 그대로 둠)
    keywords = [k for k in keywords if k and is_relevant(k["keyword"], k["news"])]
    names_by_slug = {k["slug"]: k["keyword"] for k in keywords}
    for d in days:
        d["keywords"] = {kw: v for kw, v in d["keywords"].items() if v["slug"] in names_by_slug}
    days = [d for d in days if d["keywords"]]
    kept = [dict(x) for x in latest["items"] if x["slug"] in names_by_slug]
    for i, x in enumerate(kept, 1):
        x["rank"] = i
    latest = dict(latest, items=kept)
    current_ranks = {x["keyword"]: x["rank"] for x in latest["items"]}

    write(os.path.join(SITE, "index.html"), render_index(cfg, latest, days))
    for k in keywords:
        write(os.path.join(SITE, "k", k["slug"] + ".html"), render_keyword(cfg, k, current_ranks, names_by_slug))
    for i, d in enumerate(days):
        prev_day = days[i + 1]["date"] if i + 1 < len(days) else None
        next_day = days[i - 1]["date"] if i > 0 else None
        write(os.path.join(SITE, "d", d["date"] + ".html"), render_day(cfg, d, prev_day, next_day))
    write(os.path.join(SITE, "d", "index.html"), render_days_index(cfg, days))
    render_static_pages(cfg)

    # 검색엔진용 파일
    url = cfg["siteUrl"]
    robots = "User-agent: *\nAllow: /\n"
    if url:
        entries = [(url, day_of(latest["generatedAt"])), (url + "d/", day_of(latest["generatedAt"]))]
        entries += [(f'{url}d/{d["date"]}.html', d["date"]) for d in days]
        entries += [(f'{url}k/{quote(k["slug"])}.html', day_of(k["lastSeen"])) for k in keywords]
        entries += [(url + p, day_of(latest["generatedAt"])) for p in ("about.html", "privacy.html", "contact.html")]
        sm = "".join(f"<url><loc>{e(u)}</loc><lastmod>{m}</lastmod></url>" for u, m in entries)
        write(os.path.join(SITE, "sitemap.xml"),
              f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>\n')
        robots += f"Sitemap: {url}sitemap.xml\n"
    else:
        print("알림: siteUrl이 비어 있어 sitemap.xml을 만들지 않았습니다. (GitHub Actions에서는 자동으로 채워집니다)")
    write(os.path.join(SITE, "robots.txt"), robots)
    if cfg["adsenseClient"]:
        pub = cfg["adsenseClient"].replace("ca-", "")
        write(os.path.join(SITE, "ads.txt"), f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n")
    if not cfg["contactEmail"]:
        print("알림: config.json의 contactEmail이 비어 있습니다. 애드센스 신청 전에 꼭 채워 주세요.")
    print(f"사이트 생성 완료: 검색어 페이지 {len(keywords)}개, 날짜 페이지 {len(days)}개 → site/")


def main():
    cfg = load_config()
    if "--no-fetch" not in sys.argv:
        try:
            update_data(cfg)
        except Exception as ex:   # 구글 접속이 실패해도 기존 기록으로 사이트는 만든다
            print(f"::warning::구글 트렌드 수집 실패, 기존 데이터로 사이트만 생성합니다: {ex}")
    build_site(cfg)


if __name__ == "__main__":
    main()
