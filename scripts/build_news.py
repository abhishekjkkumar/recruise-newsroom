"""Recruise Live Newsroom - news collector.

Fetches public RSS/Atom feeds from credible publishers, cleans and de-duplicates
them, sorts them into newsroom categories and writes site/news.json.

Standard library only. Run:  python scripts/build_news.py
Env:  PREVIOUS_URL  optional URL of the currently published news.json. Items from
      feeds that fail this run are carried over from it, so the TV never goes blank.
"""
import concurrent.futures as cf
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site", "news.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 RecruiseNewsroom/1.0"
NOW = dt.datetime.now(dt.timezone.utc)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def gnews(q):
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})


# (feed id, source label, url, default category)
FEEDS = [
    # Business & global
    ("bbc_business", "BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml", "business"),
    ("cnbc_top", "CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "business"),
    ("cnbc_biz", "CNBC", "https://www.cnbc.com/id/10001147/device/rss/rss.html", "business"),
    ("guardian_biz", "The Guardian", "https://www.theguardian.com/uk/business/rss", "business"),
    ("et_top", "The Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms", "business"),
    ("mint_companies", "Mint", "https://www.livemint.com/rss/companies", "business"),
    ("hbl", "BusinessLine", "https://www.thehindubusinessline.com/feeder/default.rss", "business"),
    # AI & technology
    ("bbc_tech", "BBC News", "https://feeds.bbci.co.uk/news/technology/rss.xml", "tech"),
    ("cnbc_tech", "CNBC", "https://www.cnbc.com/id/19854910/device/rss/rss.html", "tech"),
    ("et_tech", "ET Tech", "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms", "tech"),
    ("mint_ai", "Mint", "https://www.livemint.com/rss/AI", "tech"),
    ("techcrunch", "TechCrunch", "https://techcrunch.com/feed/", "tech"),
    ("verge", "The Verge", "https://www.theverge.com/rss/index.xml", "tech"),
    ("mittr", "MIT Technology Review", "https://www.technologyreview.com/feed/", "tech"),
    # India & GCC radar
    ("gn_gcc1", None, gnews('"global capability centre" OR "global capability center" OR "global capability centres" when:10d'), "gcc"),
    ("gn_gcc2", None, gnews('GCC (Bengaluru OR Hyderabad OR Pune OR Chennai OR Gurugram OR Noida OR Mumbai OR Kochi OR Ahmedabad) when:10d'), "gcc"),
    ("gn_gcc3", None, gnews('("tech centre" OR "technology centre" OR "innovation centre" OR "innovation hub" OR "new office") India (opens OR inaugurates OR expands OR launches) when:10d'), "gcc"),
    # Talent & future of work
    ("et_hr", "ETHRWorld", "https://hr.economictimes.indiatimes.com/rss/topstories", "talent"),
    ("gn_talent1", None, gnews('(layoffs OR "job cuts" OR "hiring plans" OR "hiring spree" OR "salary hike" OR workforce) India when:4d'), "talent"),
    ("gn_talent2", None, gnews('("future of work" OR "AI and jobs" OR "skills gap" OR "talent shortage" OR "return to office" OR "four-day week") when:7d'), "talent"),
    # Startup & money
    ("et_startups", "ET Tech", "https://economictimes.indiatimes.com/tech/startups/rssfeeds/78570550.cms", "startup"),
    ("inc42", "Inc42", "https://inc42.com/feed/", "startup"),
    ("yourstory", "YourStory", "https://yourstory.com/feed", "startup"),
    ("tc_startups", "TechCrunch", "https://techcrunch.com/category/startups/feed/", "startup"),
    ("gn_funding", None, gnews('startup (raises OR "funding round" OR "Series A" OR "Series B" OR "Series C" OR IPO OR acquires) India when:4d'), "startup"),
    # Curiosity corner
    ("nasa", "NASA", "https://www.nasa.gov/news-release/feed/", "curiosity"),
    ("space", "Space.com", "https://www.space.com/feeds/all", "curiosity"),
    ("sciencedaily", "ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml", "curiosity"),
    ("bbc_sci", "BBC News", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "curiosity"),
]

MAX_AGE_H = {"business": 48, "tech": 72, "gcc": 240, "talent": 120, "startup": 96, "curiosity": 336}
CAP = {"business": 45, "tech": 30, "gcc": 24, "talent": 18, "startup": 18, "curiosity": 16}

# Not suitable for an office lobby screen, or not news.
JUNK = re.compile(r"(?i)(horoscope|\blive updates?\b|\blive:|\bhighlights\b|broker.?s call|stocks? to (buy|watch)|"
                  r"share price (today|live)|sensex today|nifty today|\bquiz\b|wordle|crossword|lottery|"
                  r"^(watch|video|photos|in pics|podcast)\b|\((buy|sell|hold|accumulate)\)|sponsored|"
                  r"deals? of the day|best .* to buy|coupon|promo code|% off\b|black friday|[-–—:]\s*(business )?live$|\bas it happened\b|"
                  r"\bin charts\b|\bopinion\b|^letters?:|\bweek in review\b|daily roundup|^\d+ (books|habits|ways|tips|things|lessons|quotes)\b|"
                  r"\b(russia|ukraine|kyiv|kremlin|israel|iran|putin)\b)")
GRIM = re.compile(r"(?i)\b(killed|kills|killing|murder\w*|rape\w*|suicide|dead|deaths?|dies|died|shooting|shot dead|"
                  r"terror\w*|bomb\w*|massacre|assault\w*|abuse\w*|stabb\w*|hostage|genocide|corpse|funeral|"
                  r"porn\w*|sex(ual)?\b|missiles?|airstrikes?|air strikes?|drone attacks?|shelling|troops|warplanes?|"
                  r"gaza|hamas|hezbollah|isis|militants?|injured|wounded|casualt\w*|arrest\w*|jailed|convicted)")
GCC_FALSE = re.compile(r"(?i)(greater chennai|chennai corp|corporation|\bGCC (council|commissioner|ward|zone|budget|polls?)\b|bird hits?)")
GULF = re.compile(r"(?i)\b(gulf|saudi|uae|qatar|oman|kuwait|bahrain|dubai|abu dhabi|riyadh|doha)\b")
GCC_HINT = re.compile(r"(?i)(global capability|capability cent(re|er)|\bGCCs?\b|global in-house cent|"
                      r"(tech(nology)?|innovation|engineering|development|delivery|R&D) (cent(re|er)|hub|campus)\b)")
INDIA_HINT = re.compile(r"(?i)\b(india|indian|bengaluru|bangalore|hyderabad|pune|chennai|mumbai|gurugram|gurgaon|"
                        r"noida|delhi|ncr|kochi|ahmedabad|coimbatore|kolkata|jaipur|indore|thiruvananthapuram|mangaluru|vizag)\b")
TALENT_HINT = re.compile(r"(?i)\b(layoffs?|laid off|job cuts?|hiring|hires|recruit\w*|workforce|employees|headcount|"
                         r"salar(y|ies)|appraisal|attrition|talent|skills?|upskill\w*|jobs report|unemployment|"
                         r"return to office|work from home|wfh|hybrid work|chro|gig workers?)\b")
FUND_HINT = re.compile(r"(?i)\b(raises?|raised|funding|series [a-f]\b|seed round|pre-seed|valuation|unicorn|ipo|"
                       r"acquires|acquisition|venture|vc fund|investors?)\b")
AI_HINT = re.compile(r"(?i)\b(AI|artificial intelligence|genai|openai|anthropic|chatgpt|claude|gemini|llm|nvidia|"
                     r"chip\w*|semiconductor|robot\w*|cyber\w*|cloud|quantum|data cent(re|er)s?)\b")
CURIO_GOOD = re.compile(r"(?i)\b(first|launch\w*|discover\w*|invent\w*|found(ed)?|open(ed|s)?|record|patent\w*|"
                        r"premiere\w*|published|introduc\w*|completed|establish\w*|land(ed|ing)|flight|signed)\b")


def fetch(url, timeout=20, limit=3_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-IN,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit)


def local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def clean_text(s, n=None):
    if not s:
        return ""
    s = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(html.unescape(s))
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(?i)\s*(the post .* appeared first on .*|continue reading\.?|read more\.?|\[…\]|\[\.\.\.\])$", "", s).strip()
    if n and len(s) > n:
        s = s[:n].rsplit(" ", 1)[0].rstrip(",;:-–— ") + "…"
    return s


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
    except Exception:
        d = None
    if d is None:
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def best_image(el, desc_html):
    cands = []
    for c in el.iter():
        t = local(c.tag)
        if t in ("content", "thumbnail") and c.get("url"):
            medium = (c.get("medium") or c.get("type") or "image").lower()
            if "image" in medium or re.search(r"\.(jpe?g|png|webp)", c.get("url"), re.I):
                try:
                    w = int(c.get("width") or 0)
                except ValueError:
                    w = 0
                cands.append((w or (300 if t == "thumbnail" else 800), c.get("url")))
        elif t == "enclosure" and c.get("url") and "image" in (c.get("type") or "image"):
            cands.append((700, c.get("url")))
    if not cands and desc_html:
        m = re.search(r"<img[^>]+src=[\"']([^\"']+)", desc_html)
        if m:
            cands.append((500, html.unescape(m.group(1))))
    if not cands:
        return ""
    cands.sort(key=lambda x: -x[0])
    url = cands[0][1].strip()
    # Ask BBC's image service for a larger rendition
    url = re.sub(r"(ichef\.bbci\.co\.uk/(?:ace|news)/(?:standard|ws)/)\d+/", r"\g<1>976/", url)
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith("https://") else ""


def parse_feed(fid, source, raw, cat):
    txt = raw.decode("utf-8", "ignore")
    txt = re.sub(r"&(?!(?:[a-zA-Z]+|#\d+|#x[0-9a-fA-F]+);)", "&amp;", txt)
    root = ET.fromstring(txt.encode("utf-8"))
    out = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        f = {"title": "", "link": "", "desc": "", "date": "", "src": "", "content": ""}
        for c in el:
            t = local(c.tag)
            if t == "title":
                f["title"] = c.text or ""
            elif t == "link":
                f["link"] = f["link"] or (c.text or "").strip() or (c.get("href") if c.get("rel", "alternate") == "alternate" else "") or ""
            elif t in ("description", "summary"):
                f["desc"] = c.text or ""
            elif t == "encoded" or (t == "content" and not c.get("url")):
                f["content"] = c.text or ""
            elif t in ("pubdate", "published", "date") and not f["date"]:
                f["date"] = c.text or ""
            elif t == "updated" and not f["date"]:
                f["date"] = c.text or ""
            elif t == "source":
                f["src"] = c.text or ""
        title = clean_text(f["title"])
        link = f["link"].strip()
        if not title or not link.startswith("http"):
            continue
        src = source
        summary = clean_text(f["desc"] or f["content"], 260)
        if source is None:  # Google News: "Headline - Publisher"
            src = clean_text(f["src"])
            if not src and " - " in title:
                src = title.rsplit(" - ", 1)[1]
            if src.startswith("http"):
                src = re.sub(r"^https?://(www\.)?", "", src).split("/")[0]
            while src and title.endswith(" - " + src):
                title = title[: -len(" - " + src)].strip()
            title = re.sub(r"\s+[-|]\s+[A-Z][\w.&' ]{1,30}$", "", title) if " - " in title else title
            summary = ""
        if summary and (summary.lower().startswith(title.lower()[:40]) and len(summary) < len(title) + 30):
            summary = ""
        out.append({
            "title": title,
            "summary": summary,
            "source": src or "",
            "url": link,
            "img": best_image(el, (f["desc"] or "") + (f["content"] or "")),
            "ts": parse_date(f["date"]),
            "feed": fid,
            "cat": cat,
        })
    return out


def classify(it):
    """Move stories into the radar sections where the headline clearly belongs."""
    text = it["title"] + " " + it["summary"]
    cat = it["cat"]
    if cat == "gcc":
        if GULF.search(text) and not re.search(r"(?i)capability", text):
            return None
        if GCC_FALSE.search(text) or not GCC_HINT.search(it["title"]) or not INDIA_HINT.search(text):
            return None
        return "gcc"
    if cat in ("business", "tech") and GCC_HINT.search(it["title"]) and INDIA_HINT.search(text) and not GULF.search(text):
        return "gcc"
    if cat == "talent" and not TALENT_HINT.search(text):
        return None
    if cat in ("business", "tech") and TALENT_HINT.search(it["title"]) and re.search(
            r"(?i)\b(layoff|laid off|job cuts?|hiring|hires|workforce|salar|attrition|employees)\b", it["title"]):
        return "talent"
    if cat == "startup" and it["feed"].startswith("gn_") and not FUND_HINT.search(text):
        return None
    if cat == "business" and AI_HINT.search(it["title"]) and it["feed"] not in ("bbc_world",):
        return "tech"
    return cat


STOP = set("a an the of to in on for and or with at by from as is are was be its it this that after over into new says say amid".split())


def key_words(title):
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in STOP and len(w) > 2}


def og_image(url):
    try:
        page = fetch(url, timeout=8, limit=400_000).decode("utf-8", "ignore")
    except Exception:
        return ""
    for pat in (r'<meta[^>]+property=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)'):
        m = re.search(pat, page, re.I)
        if m:
            u = html.unescape(m.group(1)).strip()
            if u.startswith("//"):
                u = "https:" + u
            if u.startswith("https://") and not re.search(r"(?i)(logo|default|placeholder|favicon)", u):
                return u
    return ""


def on_this_day():
    d = NOW.astimezone(IST)
    url = f"https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/selected/{d.month:02d}/{d.day:02d}"
    data = json.loads(fetch(url, timeout=20))
    out = []
    for ev in data.get("selected", []):
        text = clean_text(ev.get("text", ""))
        if not text or GRIM.search(text) or re.search(r"(?i)\b(war|battle|invad\w*|army|coup|riot|earthquake|disaster|crash\w*|execut\w*|attack\w*)\b", text):
            continue
        if not CURIO_GOOD.search(text):
            continue
        pages = ev.get("pages") or []
        p = pages[0] if pages else {}
        link = ((p.get("content_urls") or {}).get("desktop") or {}).get("page") or "https://en.wikipedia.org/wiki/Wikipedia:Selected_anniversaries"
        img = (p.get("originalimage") or p.get("thumbnail") or {}).get("source", "")
        if img and not img.startswith("https://"):
            img = ""
        out.append({"title": text, "summary": clean_text(p.get("extract", ""), 220), "source": "Wikipedia · On this day",
                    "url": link, "img": img, "ts": NOW, "feed": "wiki_otd", "cat": "curiosity", "year": ev.get("year")})
    return out[:6]


def main():
    previous = {}
    prev_url = os.environ.get("PREVIOUS_URL")
    if prev_url:
        try:
            previous = json.loads(fetch(prev_url + "?t=" + str(int(NOW.timestamp())), timeout=20))
            print("previous news.json loaded")
        except Exception as e:
            print("no previous news.json:", e)
    elif os.path.exists(OUT):
        try:
            previous = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            previous = {}

    items, ok, failed = [], [], []

    def run(feed):
        fid, src, url, cat = feed
        return fid, parse_feed(fid, src, fetch(url), cat)

    with cf.ThreadPoolExecutor(10) as ex:
        futs = {ex.submit(run, f): f for f in FEEDS}
        for fu in cf.as_completed(futs):
            fid = futs[fu][0]
            try:
                _, got = fu.result()
                items.extend(got[:30])
                ok.append(fid)
            except Exception as e:
                failed.append(fid)
                print(f"FEED FAILED {fid}: {e}", file=sys.stderr)
    try:
        items.extend(on_this_day())
        ok.append("wiki_otd")
    except Exception as e:
        failed.append("wiki_otd")
        print("FEED FAILED wiki_otd:", e, file=sys.stderr)

    # Carry over last good items from feeds that failed this time.
    if previous and failed:
        for cat_items in (previous.get("categories") or {}).values():
            for p in cat_items:
                if p.get("feed") in failed:
                    p = dict(p)
                    p["ts"] = parse_date(p.get("ts"))
                    items.append(p)

    # Clean, filter, classify
    kept = []
    for it in items:
        if not it.get("ts"):
            continue
        if it["ts"] > NOW + dt.timedelta(hours=1):
            continue
        text = it["title"] + " " + (it.get("summary") or "")
        if JUNK.search(it["title"]) or GRIM.search(text):
            continue
        if len(it["title"]) < 25 or len(it["title"]) > 220:
            continue
        cat = classify(it)
        if not cat:
            continue
        it["cat"] = cat
        if NOW - it["ts"] > dt.timedelta(hours=MAX_AGE_H[cat]):
            continue
        kept.append(it)

    # De-duplicate near-identical headlines; prefer the version with an image, then the newest.
    kept.sort(key=lambda x: (0 if x["img"] else 1, -x["ts"].timestamp()))
    final, seen = [], []
    seen_urls = set()
    for it in kept:
        if it["url"] in seen_urls:
            continue
        kw = key_words(it["title"])
        if any(len(kw & s) / max(1, len(kw | s)) >= 0.5 for s in seen):
            continue
        seen.append(kw)
        seen_urls.add(it["url"])
        final.append(it)

    cats = {c: [] for c in CAP}
    for it in sorted(final, key=lambda x: -x["ts"].timestamp()):
        if len(cats[it["cat"]]) < CAP[it["cat"]]:
            cats[it["cat"]].append(it)

    # Fill missing images from the article's own og:image (publisher pages only).
    need = [it for c in cats.values() for it in c[:14] if not it["img"] and "news.google.com" not in it["url"]]
    prev_imgs = {p.get("url"): p.get("img") for c in (previous.get("categories") or {}).values() for p in c if p.get("img")}
    todo = []
    for it in need:
        if prev_imgs.get(it["url"]):
            it["img"] = prev_imgs[it["url"]]
        else:
            todo.append(it)
    with cf.ThreadPoolExecutor(10) as ex:
        for it, img in zip(todo[:70], ex.map(lambda i: og_image(i["url"]), todo[:70])):
            it["img"] = img

    total = sum(len(v) for v in cats.values())
    if total < 25 and previous.get("categories"):
        print(f"Only {total} stories collected - keeping previous news.json", file=sys.stderr)
        return

    for c in cats.values():
        for it in c:
            it["id"] = hashlib.sha1(it["url"].encode()).hexdigest()[:12]
            it["ts"] = it["ts"].strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {
        "generated": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feeds_ok": len(ok),
        "feeds_failed": sorted(failed),
        "categories": cats,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {OUT}: " + ", ".join(f"{k}={len(v)}" for k, v in cats.items()) + f"; feeds ok={len(ok)} failed={failed}")


if __name__ == "__main__":
    main()
