/* Recruise Live Newsroom - display logic.
   Data refresh (news.json, every 10 min) and screen rotation (feature 18s, cards 14s)
   run independently. Failed fetches keep the last good data on screen, silently.

   TV-SAFE JAVASCRIPT: written in plain ES5 so it runs on old smart-TV browsers
   (Samsung Tizen, LG webOS, Android TV, Fire TV). No fetch, Promise, Intl time zones,
   Object.assign, arrow functions, let/const or template strings. */
(function () {
  "use strict";

  var CFG = {
    dataEvery: 10 * 60 * 1000,
    featureEvery: 18000,
    latestEvery: 16000,
    cardEvery: 14000,
    tickerSpeed: 85,            // px per second
    hardReloadEvery: 8 * 3600 * 1000,
    istOffsetMin: 330           // India Standard Time = UTC+5:30, no daylight saving
  };

  // Category colours: Recruise primary + secondary palette (written out for old browsers)
  var CATS = {
    gcc:       { label: "India & GCC Radar",   color: "#7747FF" },
    hiring:    { label: "Hiring & Layoffs",    color: "#ED8C1D" },
    ta:        { label: "Talent & Leadership", color: "#DF3A5B" },
    tech:      { label: "AI & Technology",     color: "#19B4CC" },
    startup:   { label: "Startups & Funding",  color: "#18BF71" },
    business:  { label: "India Business",      color: "#2957E0" },
    world:     { label: "Global Business",     color: "#A58BFF" },
    economy:   { label: "Economy",             color: "#FFD2BA" },
    curiosity: { label: "Curiosity Corner",    color: "#EEBA2B" },
    recruise:  { label: "Recruise Corner",     color: "#FFD2BA" },
    gccindex:  { label: "GCC Research · This Week", color: "#7747FF" },
    talent:    { label: "Hiring & Layoffs",    color: "#ED8C1D" }
  };
  // Lighter text versions so small labels stay readable on the dark panels
  var TEXT_COLOR = { gcc: "#A58BFF", gccindex: "#A58BFF", business: "#7FA0FF" };
  function catColor(cat) { return (CATS[cat] || CATS.business).color; }
  function catText(cat) { return TEXT_COLOR[cat] || catColor(cat); }

  // Featured-story mix, weighted to Recruise's world:
  // GCC 20% · Hiring 15% · AI & tech 15% · India business 10% · Startups 10% · Talent 10% · Global 10% · Economy 10%
  var FEATURE_PATTERN = ["gcc", "hiring", "tech", "business", "gccindex", "ta", "startup", "world", "hiring", "gcc",
    "tech", "economy", "business", "gcc", "hiring", "startup", "ta", "tech", "world", "gccindex"];
  // When a section runs dry, fill from these in order: India & GCC first, then foreign business, then economy
  var FALLBACK = ["gcc", "hiring", "ta", "business", "world", "economy", "tech", "startup"];
  var CARD_SLOTS = [
    { cats: ["gcc", "gcc", "gccindex"] },
    { cats: ["hiring"] },
    { cats: ["ta", "business"] },
    { cats: ["tech", "startup", "economy"] },
    { cats: ["curiosity", "recruise"] }
  ];

  var state = {
    news: null, recruise: [], gccindex: [], version: null, generated: null,
    badImg: {}, okImg: {}, ptr: {}, recent: [], featureIdx: 0,
    latestPage: 0, cardPtr: [0, 0, 0, 0, 0], activeSlide: 0, currentFeature: null
  };

  function $(id) { return document.getElementById(id); }
  function now() { return new Date().getTime(); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function each(arr, fn) { for (var i = 0; i < arr.length; i++) fn(arr[i], i); }
  function keys(o) { var k = []; for (var p in o) if (Object.prototype.hasOwnProperty.call(o, p)) k.push(p); return k; }
  function addClass(el, c) { if ((" " + el.className + " ").indexOf(" " + c + " ") < 0) el.className = (el.className + " " + c).replace(/^\s+/, ""); }
  function removeClass(el, c) { el.className = (" " + el.className + " ").replace(" " + c + " ", " ").replace(/^\s+|\s+$/g, ""); }
  function setTransform(el, v) { el.style.webkitTransform = v; el.style.transform = v; }
  function setTransition(el, v) { el.style.webkitTransition = v; el.style.transition = v; }
  var raf = window.requestAnimationFrame || window.webkitRequestAnimationFrame ||
    function (cb) { return setTimeout(function () { cb(now()); }, 33); };

  /* ---------- Fit the 1920x1080 stage to any screen ---------- */
  function fit() {
    var w = window.innerWidth || document.documentElement.clientWidth;
    var h = window.innerHeight || document.documentElement.clientHeight;
    setTransform($("stage"), "scale(" + Math.min(w / 1920, h / 1080) + ")");
  }

  /* ---------- Time (India Standard Time, computed by hand) ---------- */
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  function ist(d) {
    var t = (d instanceof Date ? d.getTime() : d) + CFG.istOffsetMin * 60000;
    var x = new Date(t);
    return { y: x.getUTCFullYear(), mo: x.getUTCMonth(), d: x.getUTCDate(), wd: x.getUTCDay(), h: x.getUTCHours(), mi: x.getUTCMinutes() };
  }
  function hm(p) {
    var h = p.h % 12 || 12, m = p.mi < 10 ? "0" + p.mi : "" + p.mi;
    return { t: h + ":" + m, ap: p.h < 12 ? "AM" : "PM" };
  }
  function parseISO(s) {
    if (!s) return NaN;
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(s);
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) : new Date(s).getTime();
  }
  function tickClock() {
    var p = ist(new Date()), c = hm(p);
    $("clock").innerHTML = c.t + " <small>" + c.ap + " IST</small>";
    $("date").innerHTML = DAYS[p.wd] + ", " + p.d + " " + MONTHS[p.mo] + " " + p.y;
  }
  function shortDate(t) { var p = ist(t); return p.d + " " + MONTHS[p.mo].slice(0, 3); }
  function stamp(t) { var p = ist(t); return p.d + " " + MONTHS[p.mo].slice(0, 3) + " " + p.y; }
  function ago(iso) {
    var t = parseISO(iso), m = Math.round((now() - t) / 60000);
    if (isNaN(m)) return "";
    if (m < 2) return "Just now";
    if (m < 60) return m + " min ago";
    var h = Math.round(m / 60);
    if (h < 24) return h + (h === 1 ? " hr ago" : " hrs ago");
    return shortDate(t);
  }

  /* ---------- Images: never show a broken image ---------- */
  function probe(url, cb) {
    if (!url || state.badImg[url]) return cb(false);
    if (state.okImg[url]) return cb(true);
    var im = new Image(), done = false;
    try { im.referrerPolicy = "no-referrer"; } catch (e) {}
    var timer = setTimeout(function () { if (!done) { done = true; cb(false); } }, 9000);
    im.onload = function () {
      if (done) return; done = true; clearTimeout(timer);
      var ok = (im.naturalWidth || im.width) >= 120 && (im.naturalHeight || im.height) >= 80;
      if (ok) state.okImg[url] = 1; else state.badImg[url] = 1;
      cb(ok);
    };
    im.onerror = function () { if (!done) { done = true; clearTimeout(timer); state.badImg[url] = 1; cb(false); } };
    im.src = url;
  }
  function art(cat, small) {
    return '<div class="art' + (small ? " small" : "") + '"><div class="lines"></div><img class="mark" src="assets/mark_white.png" alt="">' +
      (small ? "" : '<div class="art-cat">' + esc((CATS[cat] || {}).label || "") + "</div>") + "</div>";
  }
  function bg(url) { return "url('" + url.replace(/'/g, "%27").replace(/\)/g, "%29").replace(/\(/g, "%28") + "')"; }
  function fillImage(el, it, small) {
    el.style.backgroundImage = "";
    el.innerHTML = art(it.cat, small);
    if (!it.img) return;
    probe(it.img, function (ok) {
      if (ok) { el.innerHTML = ""; el.style.backgroundImage = bg(it.img); }
    });
  }

  /* ---------- Data (XMLHttpRequest works everywhere) ---------- */
  function getJSON(url, ok, fail) {
    var x;
    try {
      x = new XMLHttpRequest();
      x.open("GET", url + (url.indexOf("?") < 0 ? "?" : "&") + "t=" + now(), true);
      x.timeout = 20000;
    } catch (e) { return fail && fail(); }
    x.onreadystatechange = function () {
      if (x.readyState !== 4) return;
      if (x.status >= 200 && x.status < 300) {
        var d = null;
        try { d = JSON.parse(x.responseText); } catch (e) { return fail && fail(); }
        ok(d);
      } else if (fail) fail();
    };
    try { x.send(); } catch (e) { if (fail) fail(); }
  }
  function list(cat) {
    if (cat === "recruise") return state.recruise;
    if (cat === "gccindex") return state.gccindex;
    return (state.news && state.news.categories && state.news.categories[cat]) || [];
  }
  function remember(id) {
    state.recent.push(id);
    if (state.recent.length > 60) state.recent.shift();
  }
  function seen(it) { for (var i = 0; i < state.recent.length; i++) if (state.recent[i] === it.id) return true; return false; }
  // strict: only return a story not shown recently (null if the section has run dry)
  function nextFrom(cat, preferImage, strict) {
    var arr = list(cat);
    if (!arr.length) return null;
    var p = state.ptr[cat] || 0;
    var passes = [
      function (it) { return !seen(it) && (!preferImage || (it.img && !state.badImg[it.img])); },
      function (it) { return !seen(it); }
    ];
    if (!strict) passes.push(function () { return true; });
    for (var pass = 0; pass < passes.length; pass++) {
      for (var i = 0; i < arr.length; i++) {
        var it = arr[(p + i) % arr.length];
        if (!passes[pass](it)) continue;
        state.ptr[cat] = (p + i + 1) % arr.length;
        return it;
      }
    }
    return null;
  }
  // Slow news day: when a section has nothing new, fall back in Recruise's priority order
  function pick(cat, preferImage) {
    var it = nextFrom(cat, preferImage, true);
    for (var i = 0; !it && i < FALLBACK.length; i++) it = nextFrom(FALLBACK[i], preferImage, true);
    return it || nextFrom(cat, preferImage, false) || nextFrom("gcc", preferImage, false);
  }

  function loadData(first) {
    var pending = 4;

    // GCC Index weekly brief, pasted in by the team each Monday (credited quote, not a data feed)
    getJSON("gcc_weekly.json", function (d) {
      var out = [], t = now();
      function add(list, section, from, maxDays, when, url) {
        if (!list || !from || isNaN(parseISO(from + "T00:00:00"))) return;
        if (t - parseISO(from + "T00:00:00") > maxDays * 86400000) return;   // never show a stale brief
        each(list, function (x, i) {
          if (!x || !x.title) return;
          out.push({ id: "gi" + section + i, cat: "gccindex", title: x.title, summary: x.detail || "",
            source: "GCC Index", label: x.label || "", when: when, url: url, img: "", ts: null });
        });
      }
      if (d) {
        var wk = d.week_of ? "Week of " + stamp(parseISO(d.week_of + "T00:00:00")) : "";
        add(d.items, "w", d.week_of, 10, wk, d.url);
        if (d.monthly) add(d.monthly.items, "m", d.monthly.month_start, 40, d.monthly.month + " report", d.monthly.url);
      }
      state.gccindex = out;
      done();
    }, done);
    function done() { if (--pending === 0) { updatedLabel(); if (first) start(); } }

    getJSON("news.json", function (d) {
      if (d && d.categories) {
        var n = 0; each(keys(d.categories), function (k) { n += d.categories[k].length; });
        if (n >= 10) {
          var changed = !state.news || state.news.generated !== d.generated;
          state.news = d; state.generated = d.generated;
          if (changed) buildTicker();
        }
      }
      done();
    }, done);   // on failure: keep last good data

    getJSON("recruise.json", function (d) {
      var today = now() - 86400000, out = [];
      each((d && d.items) || [], function (x, i) {
        if (!x || !x.title) return;
        if (x.until && parseISO(x.until + "T23:59:59") < today) return;
        out.push({ id: "rc" + i, cat: "recruise", title: x.title, summary: x.text || "", source: "Recruise",
          img: x.image || "", label: x.label || "Recruise Corner", ts: null });
      });
      state.recruise = out;
      done();
    }, done);

    getJSON("version.json", function (v) {
      if (v && v.build) {
        if (state.version && state.version !== v.build) { location.reload(); return; }
        state.version = v.build;
      }
      done();
    }, done);
  }
  function updatedLabel() {
    if (!state.generated) { $("updated").innerHTML = "Loading the latest news&hellip;"; return; }
    var c = hm(ist(parseISO(state.generated)));
    $("updated").innerHTML = "Updated " + c.t + " " + c.ap + " IST";
  }

  /* ---------- Feature ---------- */
  function showFeature() {
    if (!state.news) return;
    var cat = FEATURE_PATTERN[state.featureIdx % FEATURE_PATTERN.length];
    state.featureIdx++;
    var it = pick(cat, true);
    if (!it) return;
    remember(it.id);

    var slideId = state.activeSlide === 0 ? "fB" : "fA";
    var other = state.activeSlide === 0 ? "fA" : "fB";
    var el = $(slideId);
    var when = it.year ? ("On this day &middot; " + it.year) :
      (it.when ? esc(it.when) : (ago(it.ts) + '<span class="sep">/</span>' + stamp(parseISO(it.ts))));
    el.innerHTML =
      '<div class="f-img"></div><div class="f-shade"></div>' +
      '<div class="f-text">' +
        '<div class="cat"><span class="pin" style="background:' + catColor(it.cat) + '"></span>' + esc((CATS[it.cat] || CATS.business).label) + "</div>" +
        '<div class="f-title">' + esc(it.title) + "</div>" +
        (it.summary ? '<div class="f-sum">' + esc(it.summary) + "</div>" : "") +
        '<div class="meta"><b>' + esc(it.source) + '</b><span class="sep">/</span>' + when + "</div>" +
      "</div>";
    var imgEl = el.getElementsByTagName("div")[0];

    function reveal() {
      addClass(el, "on");
      removeClass($(other), "on");
      state.activeSlide = slideId === "fA" ? 0 : 1;
      var bar = $("fBar");
      setTransition(bar, "none"); bar.style.width = "0";
      bar.offsetWidth; // restart the progress bar
      setTransition(bar, "width " + (CFG.featureEvery - 400) + "ms linear");
      bar.style.width = "100%";
    }
    if (it.img && !state.badImg[it.img]) {
      probe(it.img, function (ok) {
        if (ok) imgEl.style.backgroundImage = bg(it.img);
        else imgEl.innerHTML = art(it.cat);
        reveal();
      });
    } else { imgEl.innerHTML = art(it.cat); reveal(); }
    state.currentFeature = it.id;
  }

  /* ---------- Latest coverage ---------- */
  function allRecent() {
    var out = [];
    if (!state.news) return out;
    each(keys(state.news.categories), function (k) {
      if (k === "curiosity") return;
      each(state.news.categories[k].slice(0, 8), function (x) { out.push(x); });
    });
    out.sort(function (a, b) { return parseISO(b.ts) - parseISO(a.ts); });
    return out.slice(0, 20);
  }
  function showLatest() {
    var items = [];
    each(allRecent(), function (x) { if (x.id !== state.currentFeature) items.push(x); });
    if (!items.length) return;
    var per = 3, pages = Math.max(1, Math.ceil(items.length / per));
    var page = state.latestPage % pages; state.latestPage++;
    var slice = items.slice(page * per, page * per + per);
    var box = $("latestList");
    addClass(box, "fade");
    setTimeout(function () {
      var html = "";
      each(slice, function (it, i) {
        html += '<div class="l-item' + (i === slice.length - 1 ? " last" : "") + '"><div class="thumb" id="lt' + i + '"></div><div class="l-body">' +
          '<div class="l-cat" style="color:' + catText(it.cat) + '">' + esc((CATS[it.cat] || CATS.business).label) + "</div>" +
          '<div class="l-title">' + esc(it.title) + "</div>" +
          '<div class="l-meta"><b>' + esc(it.source) + "</b> &middot; " + ago(it.ts) + "</div></div></div>";
      });
      box.innerHTML = html;
      each(slice, function (it, i) { fillImage($("lt" + i), it, true); });
      removeClass(box, "fade");
    }, 700);
  }

  /* ---------- Cards ---------- */
  function buildCards() {
    var html = "";
    each(CARD_SLOTS, function (s, i) {
      html += '<div class="card" id="card' + i + '" style="border-top-color:' + catColor(s.cats[0]) + '"><div class="inner" id="ci' + i + '"></div></div>';
    });
    $("cards").innerHTML = html;
  }
  function showCard(i) {
    var slot = CARD_SLOTS[i], cats = [];
    each(slot.cats, function (c) { if (list(c).length) cats.push(c); });
    if (!cats.length) return;
    var cat = cats[state.cardPtr[i] % cats.length];
    state.cardPtr[i]++;
    var it = nextFrom(cat, false, false);
    if (!it) return;
    var card = $("card" + i), inner = $("ci" + i);
    var head = cat === "recruise" ? (it.label || "Recruise Corner") :
      (cat === "curiosity" ? (it.year ? "On this day &middot; " + it.year : "Did You Know?") : esc(CATS[cat].label));
    var sub = cat === "curiosity" ? "Curiosity Corner" : (cat === "recruise" ? "Inside Recruise" : (cat === "gccindex" ? (it.label || "") : ""));
    var meta = it.ts ? "<b>" + esc(it.source) + "</b> &middot; " + ago(it.ts) : "<b>" + esc(it.source) + "</b>";
    if (it.year) meta = "<b>Wikipedia</b> &middot; " + stamp(now());
    if (it.when) meta = "<b>" + esc(it.source) + "</b> &middot; " + esc(it.when);
    addClass(inner, "fade");
    setTimeout(function () {
      card.style.borderTopColor = catColor(cat);
      inner.innerHTML = '<div class="c-head"><span class="c-cat" style="color:' + catText(cat) + '">' + head + "</span>" +
        (sub ? '<span class="c-sub">' + esc(sub) + "</span>" : "") + "</div>" +
        '<div class="c-row"><div class="c-thumb" id="ct' + i + '"></div><div class="c-title">' + esc(it.title) + "</div></div>" +
        '<div class="c-meta">' + meta + "</div>";
      fillImage($("ct" + i), it, true);
      removeClass(inner, "fade");
    }, 800);
  }

  /* ---------- Ticker ---------- */
  var tick = { x: 0, w: 0, last: 0, pending: null };
  function tickerHTML() {
    var out = [], used = {};
    var order = ["gcc", "hiring", "business", "tech", "ta", "world", "startup", "gcc", "economy", "hiring", "tech", "business"];
    for (var round = 0; round < 4; round++) {
      each(order, function (cat) {
        var arr = list(cat);
        for (var i = 0; i < arr.length; i++) {
          if (!used[arr[i].id]) { used[arr[i].id] = 1; out.push(arr[i]); break; }
        }
      });
    }
    var html = "";
    each(out, function (it) {
      html += '<span class="t-item"><span class="pin" style="background:' + catColor(it.cat) + '"></span>' +
        '<span class="t-src">' + esc(it.source) + "</span>" + esc(it.title) + "</span>";
    });
    return html;
  }
  function buildTicker() {
    var html = tickerHTML();
    if (!html) return;
    if (!tick.w) applyTicker(html); else tick.pending = html; // swap at the loop point, no jump
  }
  function applyTicker(html) {
    var t = $("tTrack");
    t.innerHTML = html + html;
    tick.w = t.scrollWidth / 2 || t.offsetWidth / 2;
    tick.x = 0;
  }
  function runTicker(ts) {
    ts = ts || now();
    if (!tick.last) tick.last = ts;
    var dt = Math.min(100, ts - tick.last); tick.last = ts;
    if (tick.w) {
      tick.x += CFG.tickerSpeed * dt / 1000;
      if (tick.x >= tick.w) {
        if (tick.pending) { applyTicker(tick.pending); tick.pending = null; }
        else tick.x -= tick.w;
      }
      setTransform($("tTrack"), "translate3d(" + (-tick.x).toFixed(1) + "px,0,0)");
    }
    raf(runTicker);
  }

  /* ---------- Start ---------- */
  var started = false;
  function start() {
    if (started) return;
    if (!state.news) { setTimeout(function () { loadData(true); }, 30000); return; }
    started = true;
    showFeature();
    setInterval(showFeature, CFG.featureEvery);
    showLatest();
    setInterval(showLatest, CFG.latestEvery);
    each(CARD_SLOTS, function (s, i) {
      showCard(i);
      setTimeout(function () { setInterval(function () { showCard(i); }, CFG.cardEvery); }, i * 2600);
    });
  }

  function keepAwake() {
    try { if (navigator.wakeLock) navigator.wakeLock.request("screen")["catch"](function () {}); } catch (e) {}
  }

  fit();
  window.onresize = fit;
  tickClock();
  setInterval(tickClock, 1000);
  buildCards();
  raf(runTicker);
  loadData(true);
  setInterval(function () { loadData(false); }, CFG.dataEvery);
  setInterval(updatedLabel, 60000);
  keepAwake();
  document.addEventListener("visibilitychange", function () { if (!document.hidden) keepAwake(); }, false);
  /* ---------- Full screen: press OK on the TV remote (or click / any key) ---------- */
  // Browsers only allow full screen after a button press, so we listen for one.
  function isFull() {
    return !!(document.fullscreenElement || document.webkitFullscreenElement || document.webkitIsFullScreen ||
      document.mozFullScreenElement || document.msFullscreenElement);
  }
  function goFull() {
    if (isFull()) return;
    var d = document.documentElement;
    var f = d.requestFullscreen || d.webkitRequestFullscreen || d.webkitRequestFullScreen || d.mozRequestFullScreen || d.msRequestFullscreen;
    try { var r = f && f.call(d); if (r && r["catch"]) r["catch"](function () {}); } catch (e) {}
    hideHint();
  }
  function canFull() {
    var d = document.documentElement;
    return !!(d.requestFullscreen || d.webkitRequestFullscreen || d.webkitRequestFullScreen || d.mozRequestFullScreen || d.msRequestFullscreen);
  }
  function hideHint() { var h = $("fsHint"); if (h) h.style.opacity = "0"; }
  document.addEventListener("click", goFull, false);
  document.addEventListener("keydown", goFull, false);
  if (canFull() && !isFull()) {
    var hint = $("fsHint");
    if (hint) {
      hint.style.opacity = "1";
      setTimeout(hideHint, 12000);
    }
  }
  // Periodic clean reload keeps long-running TV browsers fresh; only when the site is reachable.
  setTimeout(function () {
    getJSON("version.json", function () { location.reload(); });
  }, CFG.hardReloadEvery);
})();
