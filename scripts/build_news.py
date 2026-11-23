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
# Weighted to Recruise's world: GCCs, hiring & layoffs, talent acquisition & leadership,
# AI & tech, startups & funding, and only the business news that moves companies and jobs.
HR_SITES = "(site:peoplematters.in OR site:hrkatha.com OR site:hr.economictimes.indiatimes.com OR site:shrm.org OR site:hrdive.com)"
IT_MAJORS = ('Infosys OR TCS OR Wipro OR HCLTech OR "Tech Mahindra" OR LTIMindtree OR Accenture OR Cognizant '
             'OR Capgemini OR Deloitte OR Genpact OR Coforge OR Persistent OR Mphasis')
CITIES = "(Bengaluru OR Bangalore OR Hyderabad OR Pune OR Chennai OR Gurugram OR Noida OR Mumbai OR Kochi OR Ahmedabad OR Coimbatore OR Mangaluru)"
FEEDS = [
    # India & GCC radar
    ("gn_gcc1", None, gnews('"global capability centre" OR "global capability center" OR "global capability centres" when:7d'), "gcc"),
    ("gn_gcc2", None, gnews('GCC ' + CITIES + ' when:7d'), "gcc"),
    ("gn_gcc3", None, gnews('("tech centre" OR "technology centre" OR "innovation centre" OR "innovation hub" OR "engineering centre" OR "new office" OR campus) India (opens OR inaugurates OR expands OR launches OR "sets up") when:7d'), "gcc"),
    ("gn_gcc4", None, gnews('("enters India" OR "India entry" OR "India operations" OR "India expansion" OR "expands in India" OR "India headcount") when:7d'), "gcc"),
    ("gn_gcc5", None, gnews('(NASSCOM OR Zinnov OR ANSR) (GCC OR "capability centre" OR report) when:14d'), "gcc"),
    # Hiring & layoffs
    ("gn_hire1", None, gnews('("plans to hire" OR "to hire" OR "hiring plans" OR "hiring spree" OR "fresher hiring" OR "campus hiring" OR "lateral hiring") India when:4d'), "hiring"),
    ("gn_hire2", None, gnews('(layoffs OR "job cuts" OR "laid off" OR "cut jobs" OR "workforce reduction") (tech OR IT OR startup OR AI OR bank) when:3d'), "hiring"),
    ("gn_hire3", None, gnews('("Naukri JobSpeak" OR foundit OR TeamLease OR Xpheno OR Quess OR "Indeed Hiring Lab" OR "white-collar hiring") when:10d'), "hiring"),
    ("gn_hire4", None, gnews('(' + IT_MAJORS + ') (hiring OR headcount OR freshers OR layoffs OR attrition OR "wage hike" OR "salary hike") when:5d'), "hiring"),
    # Talent acquisition, HR & leadership moves
    ("et_hr", "ETHRWorld", "https://hr.economictimes.indiatimes.com/rss/topstories", "ta"),
    ("gn_hrnews", None, gnews(HR_SITES + ' when:3d'), "ta"),
    ("gn_ta", None, gnews('("talent acquisition" OR recruitment OR "executive search" OR staffing OR RPO OR "skills gap" OR "talent shortage" OR "employer branding") India when:5d'), "ta"),
    ("gn_moves", None, gnews('(appoints OR appointed OR elevates OR elevated OR "named as" OR "joins as") (CHRO OR CTO OR CIO OR CEO OR "country head" OR "managing director" OR "head of GCC" OR "centre head" OR "site leader") India when:5d'), "ta"),
    ("gn_fow", None, gnews('("future of work" OR "AI and jobs" OR "AI impact on jobs" OR "return to office" OR "hybrid work" OR "four-day week" OR "salary increment") when:7d'), "ta"),
    # AI & technology
    ("mint_ai", "Mint", "https://www.livemint.com/rss/AI", "tech"),
    ("et_tech", "ET Tech", "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms", "tech"),
    ("bbc_tech", "BBC News", "https://feeds.bbci.co.uk/news/technology/rss.xml", "tech"),
    ("cnbc_tech", "CNBC", "https://www.cnbc.com/id/19854910/device/rss/rss.html", "tech"),
    ("techcrunch", "TechCrunch", "https://techcrunch.com/feed/", "tech"),
    ("verge", "The Verge", "https://www.theverge.com/rss/index.xml", "tech"),
    ("mittr", "MIT Technology Review", "https://www.technologyreview.com/feed/", "tech"),
    ("gn_ai_india", None, gnews('("AI" OR "generative AI" OR "agentic AI" OR cybersecurity OR cloud) (India OR GCC OR ' + IT_MAJORS + ') when:3d'), "tech"),
    # Startups & funding
    ("et_startups", "ET Tech", "https://economictimes.indiatimes.com/tech/startups/rssfeeds/78570550.cms", "startup"),
    ("inc42", "Inc42", "https://inc42.com/feed/", "startup"),
    ("yourstory", "YourStory", "https://yourstory.com/feed", "startup"),
    ("tc_startups", "TechCrunch", "https://techcrunch.com/category/startups/feed/", "startup"),
    ("gn_funding", None, gnews('startup (raises OR "funding round" OR "Series A" OR "Series B" OR "Series C" OR IPO OR acquires OR unicorn) India when:4d'), "startup"),
    # Business & deals (filtered to companies, deals, investment, economy)
    ("gn_itmajors", None, gnews('(' + IT_MAJORS + ') (deal OR contract OR results OR acquisition OR expansion OR CEO) when:4d'), "business"),
    ("mint_companies", "Mint", "https://www.livemint.com/rss/companies", "business"),
    ("et_top", "The Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms", "business"),
    ("hbl", "BusinessLine", "https://www.thehindubusinessline.com/feeder/default.rss", "business"),
    ("cnbc_biz", "CNBC", "https://www.cnbc.com/id/10001147/device/rss/rss.html", "business"),
    ("bbc_business", "BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml", "business"),
    # Curiosity corner (small share)
    ("nasa", "NASA", "https://www.nasa.gov/news-release/feed/", "curiosity"),
    ("space", "Space.com", "https://www.space.com/feeds/all", "curiosity"),
    ("sciencedaily", "ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml", "curiosity"),
]

MAX_AGE_H = {"gcc": 240, "hiring": 120, "ta": 168, "tech": 72, "startup": 96, "business": 48, "curiosity": 336}
CAP = {"gcc": 30, "hiring": 26, "ta": 24, "tech": 28, "startup": 22, "business": 24, "curiosity": 10}

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
HIRING_TITLE = re.compile(r"(?i)\b(layoffs?|laid off|job cuts?|cut(s|ting)? jobs|hiring|to hire|hires|headcount|freshers?|"
                          r"campus placements?|attrition|wage hike|salary hike|increments?|workforce reduction|jobs? (report|data|market))\b")
TA_TITLE = re.compile(r"(?i)\b(appoint\w*|elevat\w*|named|joins as|chro|chief people|hr head|talent acquisition|recruit\w*|"
                      r"staffing|executive search|skills? gap|upskill\w*|reskill\w*|employer brand\w*|future of work|"
                      r"hybrid work|return to office|work from office|employee experience|gig workers?)\b")
BIZ_REL = re.compile(r"(?i)\b(acqui\w*|merger|invest\w*|stake|expan\w*|ipo|earnings|results|profit|revenue|quarter|q[1-4]|"
                     r"deal|contract|order book|it services|outsourc\w*|capex|plant|factory|facility|launch\w*|ceo|board|"
                     r"economy|gdp|rbi|fed|interest rates?|inflation|rupee|tariffs?|exports?|fdi|manufacturing|"
                     r"infosys|tcs|wipro|hcl\w*|accenture|cognizant|capgemini|deloitte|pwc|kpmg|mckinsey|tata|reliance|adani|"
                     r"microsoft|google|amazon|apple|meta|nvidia|walmart|jpmorgan|goldman)\b")
MARKET_NOISE = re.compile(r"(?i)\b(sensex|nifty|stock market today|stocks to|gold (price|rate)|silver (price|rate)|crude oil price|"
                          r"petrol|diesel price|bitcoin price|market wrap|closing bell|opening bell|f&o|multibagger|penny stock|"
                          r"mutual funds? to|sip|fixed deposit|fd rates?|credit card|personal finance|tax saving|futures|"
                          r"shares (open|close|end|trade)|(asian|us|indian|global) (stocks|shares|markets)|"
                          r"stocks? (rise|fall|slump|rally|drop|jump|surge)|you can buy|best .* deals?)\b")
GOVT_JOBS = re.compile(r"(?i)\b(agnipath|agniveer|army|police|constable|ssc|upsc|psc|jssc|bpsc|rrb|railway recruitment|"
                       r"admit card|answer key|vacanc\w*|notification|govt jobs?|government jobs?|sarkari|exam|recruitment drive for|"
                       r"teachers? recruitment|minister|chef|gorkha)\b")
LOW_QUALITY_SRC = re.compile(r"(?i)(36kr|updf|global advisory|tradingkey|tradingview|wisevoter|prop news|onlinekhabar|hubbis|"
                             r"marketscreener|stocktitan|benzinga|investing\.com|globe newswire|pr newswire|einpresswire|"
                             r"openpr|newsbreak|latestly|devdiscourse|whalesbook|upstox|groww)")
GOSSIP = re.compile(r"(?i)\b(affair|spy|girlfriend|wife|husband|dating|divorce|viral video|copper|commodit\w*|"
                    r"book of records|sponge parks?|civic|garbage|storm ?water|potholes?)\b")
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
            title = re.sub(r"\s+[-|]\s+https?://\S+$", "", title)
            title = re.sub(r"\s+[-|]\s+[A-Z][\w.&' ]{1,30}$", "", title) if " - " in title else title
            src = re.sub(r"\s+-\s+.*$", "", src)  # "People Matters - India" -> "People Matters"
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
    """Sort each story into the section where Recruise's audience will care about it."""
    title = it["title"]
    text = title + " " + it["summary"]
    cat = it["cat"]
    if MARKET_NOISE.search(title) or GOSSIP.search(title):
        return None
    if cat == "curiosity":
        return cat
    from_gn = it["feed"].startswith("gn_")
    if from_gn and LOW_QUALITY_SRC.search(it["source"] or ""):
        return None
    # Search-based hiring / talent stories must touch India, tech/AI or a major employer
    if GOVT_JOBS.search(title) and (cat in ("hiring", "ta") or TA_TITLE.search(title) or HIRING_TITLE.search(title)):
        return None
    if re.search(r"(?i)^(top|best) \d+|\btop \d+ best\b", title):
        return None
    if from_gn and cat in ("hiring", "ta"):
        if not (INDIA_HINT.search(text) or AI_HINT.search(title) or BIZ_REL.search(title)):
            return None
        if it["feed"] == "gn_moves" and not INDIA_HINT.search(text):
            return None
    if cat == "gcc":
        if GULF.search(text) and not re.search(r"(?i)capability", text):
            return None
        if GCC_FALSE.search(text) or not INDIA_HINT.search(text):
            return None
        if not (GCC_HINT.search(title) or re.search(
                r"(?i)\b(office|campus|centre|center|hub|enters|expan\w*|operations|headcount|facility)\b", title)):
            return None
        return "gcc"
    # From any section: a GCC / India-centre story belongs on the GCC radar
    if GCC_HINT.search(title) and INDIA_HINT.search(text) and not GULF.search(text) and not GCC_FALSE.search(text):
        return "gcc"
    if HIRING_TITLE.search(title) and cat != "startup":
        return "hiring"
    if cat == "hiring":
        return "hiring" if TALENT_HINT.search(text) else None
    if TA_TITLE.search(title) and cat in ("business", "tech", "ta"):
        return "ta"
    if cat == "ta":
        return "ta" if (TALENT_HINT.search(text) or TA_TITLE.search(text)) else None
    if cat == "startup":
        if it["feed"].startswith("gn_") and not FUND_HINT.search(text):
            return None
        return "startup"
    if cat == "business":
        if AI_HINT.search(title):
            return "tech"
        if FUND_HINT.search(title) and re.search(r"(?i)startup", text):
            return "startup"
        return "business" if BIZ_REL.search(title) else None
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
