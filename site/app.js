/* Recruise Live Newsroom - display logic.
   Data refresh (news.json, every 10 min) and screen rotation (feature 18s, cards 14s)
   run independently. Failed fetches keep the last good data on screen, silently. */
(function () {
  "use strict";

  var CFG = {
    dataEvery: 10 * 60 * 1000,
    featureEvery: 18000,
    latestEvery: 16000,
    cardEvery: 14000,
    tickerSpeed: 85,            // px per second
    hardReloadEvery: 8 * 3600 * 1000,
    tz: "Asia/Kolkata"
  };

  var CATS = {
    gcc:       { label: "India & GCC Radar",     color: "var(--c-gcc)" },
    hiring:    { label: "Hiring & Layoffs",      color: "var(--c-talent)" },
    ta:        { label: "Talent & Leadership",   color: "var(--c-ta)" },
    tech:      { label: "AI & Technology",       color: "var(--c-tech)" },
    startup:   { label: "Startups & Funding",    color: "var(--c-startup)" },
    business:  { label: "India Business",        color: "var(--c-business)" },
    world:     { label: "Global Business",       color: "var(--c-world)" },
    economy:   { label: "Economy",               color: "var(--c-economy)" },
    curiosity: { label: "Curiosity Corner",      color: "var(--c-curiosity)" },
    recruise:  { label: "Recruise Corner",       color: "var(--c-recruise)" },
    talent:    { label: "Hiring & Layoffs",      color: "var(--c-talent)" }
  };
  // Featured-story mix, weighted to Recruise's world:
  // GCC 20% · Hiring 15% · AI & tech 15% · India business 10% · Startups 10% · Talent 10% · Global 10% · Economy 10%
  var FEATURE_PATTERN = ["gcc", "hiring", "tech", "business", "gcc", "ta", "startup", "world", "hiring", "gcc",
    "tech", "economy", "business", "gcc", "hiring", "startup", "ta", "tech", "world", "economy"];
  // When a section runs dry, fill from these in order: India & GCC first, then foreign business, then economy
  var FALLBACK = ["gcc", "hiring", "ta", "business", "world", "economy", "tech", "startup"];
  var CARD_SLOTS = [
    { cats: ["gcc"] },
    { cats: ["hiring"] },
    { cats: ["ta", "business"] },
    { cats: ["tech", "startup", "economy"] },
    { cats: ["curiosity", "recruise"] }
  ];

  var state = {
    news: null, recruise: [], version: null, generated: null,
    badImg: {}, okImg: {}, ptr: {}, recent: [], featureIdx: 0, featureCount: 0,
    latestPage: 0, cardPtr: [0, 0, 0, 0, 0], activeSlide: 0
  };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ---------- Fit 1920x1080 stage to the screen ---------- */
  function fit() {
    var s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    $("stage").style.transform = "translate(-50%, -50%) scale(" + s + ")";
  }

  /* ---------- Time ---------- */
  function fmt(d, opts) {
    try { return new Intl.DateTimeFormat("en-IN", Object.assign({ timeZone: CFG.tz }, opts)).format(d); }
    catch (e) { return d.toLocaleString(); }
  }
  function tickClock() {
    var d = new Date();
    var t = fmt(d, { hour: "numeric", minute: "2-digit", hour12: true }).replace(/\s?(am|pm)/i, function (m) { return " <small>" + m.trim().toUpperCase() + " IST</small>"; });
    $("clock").innerHTML = t;
    $("date").textContent = fmt(d, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  }
  function ago(iso) {
    var d = new Date(iso), m = Math.round((Date.now() - d.getTime()) / 60000);
    if (isNaN(m)) return "";
    if (m < 2) return "Just now";
    if (m < 60) return m + " min ago";
    var h = Math.round(m / 60);
    if (h < 24) return h + (h === 1 ? " hr ago" : " hrs ago");
    return fmt(d, { day: "numeric", month: "short" });
  }
  function stamp(iso) { return fmt(new Date(iso), { day: "numeric", month: "short", year: "numeric" }); }

  /* ---------- Images: never show a broken image ---------- */
  function probe(url) {
    return new Promise(function (resolve) {
      if (!url || state.badImg[url]) return resolve(false);
      if (state.okImg[url]) return resolve(true);
      var im = new Image(), done = false;
      im.referrerPolicy = "no-referrer";
      var timer = setTimeout(function () { if (!done) { done = true; resolve(false); } }, 9000);
      im.onload = function () {
        if (done) return; done = true; clearTimeout(timer);
        var ok = im.naturalWidth >= 120 && im.naturalHeight >= 80;
        if (ok) state.okImg[url] = 1; else state.badImg[url] = 1;
        resolve(ok);
      };
      im.onerror = function () { if (!done) { done = true; clearTimeout(timer); state.badImg[url] = 1; resolve(false); } };
      im.src = url;
    });
  }
  function art(cat, small) {
    return '<div class="art' + (small ? " small" : "") + '"><img class="mark" src="assets/mark_white.png" alt="">' +
      (small ? "" : '<div class="art-cat">' + esc((CATS[cat] || {}).label || "") + "</div>") + "</div>";
  }
  function fillImage(el, it, small) {
    el.innerHTML = art(it.cat, small);
    if (!it.img) return;
    probe(it.img).then(function (ok) {
      if (ok && el.isConnected !== false) {
        el.innerHTML = "";
        el.style.backgroundImage = 'url("' + it.img.replace(/"/g, "%22") + '")';
      }
    });
  }

  /* ---------- Data ---------- */
  function getJSON(url) {
    var sep = url.indexOf("?") < 0 ? "?" : "&";
    return fetch(url + sep + "t=" + Date.now(), { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
  }
  function list(cat) {
    if (cat === "recruise") return state.recruise;
    return (state.news && state.news.categories && state.news.categories[cat]) || [];
  }
  function remember(id) {
    state.recent.push(id);
    if (state.recent.length > 60) state.recent.shift();
  }
  // strict: only return a story not shown recently (null if the section has run dry)
  function nextFrom(cat, preferImage, strict) {
    var arr = list(cat);
    if (!arr.length) return null;
    var p = state.ptr[cat] || 0;
    var passes = [
      function (it) { return state.recent.indexOf(it.id) < 0 && (!preferImage || (it.img && !state.badImg[it.img])); },
      function (it) { return state.recent.indexOf(it.id) < 0; }
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
    var pNews = getJSON("news.json").then(function (d) {
      if (d && d.categories) {
        var n = 0; Object.keys(d.categories).forEach(function (k) { n += d.categories[k].length; });
        if (n >= 10) {
          var changed = !state.news || state.news.generated !== d.generated;
          state.news = d; state.generated = d.generated;
          if (changed) buildTicker();
        }
      }
    }).catch(function () { /* keep last good data */ });

    var pCorner = getJSON("recruise.json").then(function (d) {
      var today = new Date(); today.setHours(0, 0, 0, 0);
      state.recruise = ((d && d.items) || []).filter(function (x) {
        if (!x || !x.title) return false;
        if (x.until && new Date(x.until + "T23:59:59") < today) return false;
        return true;
      }).map(function (x, i) {
        return { id: "rc" + i, cat: "recruise", title: x.title, summary: x.text || "", source: "Recruise",
          img: x.image || "", label: x.label || "Recruise Corner", ts: null };
      });
    }).catch(function () {});

    var pVer = getJSON("version.json").then(function (v) {
      if (!v || !v.build) return;
      if (state.version && state.version !== v.build) { location.reload(); return; }
      state.version = v.build;
    }).catch(function () {});

    return Promise.all([pNews, pCorner, pVer]).then(function () {
      updatedLabel();
      if (first) start();
    });
  }
  function updatedLabel() {
    if (!state.generated) { $("updated").textContent = "Loading the latest news…"; return; }
    $("updated").textContent = "Updated " + fmt(new Date(state.generated), { hour: "numeric", minute: "2-digit", hour12: true }).toUpperCase() + " IST";
  }

  /* ---------- Feature ---------- */
  function showFeature() {
    if (!state.news) return;
    var cat = FEATURE_PATTERN[state.featureIdx % FEATURE_PATTERN.length];
    state.featureIdx++;
    var it = pick(cat, true);
    if (!it) return;
    remember(it.id);
    state.featureCount++;

    var slideId = state.activeSlide === 0 ? "fB" : "fA";
    var other = state.activeSlide === 0 ? "fA" : "fB";
    var el = $(slideId);
    var c = CATS[it.cat] || CATS.business;
    var when = it.year ? ("On this day · " + it.year) : (ago(it.ts) + '<span class="sep">/</span>' + stamp(it.ts));
    el.innerHTML =
      '<div class="f-img"></div><div class="f-shade"></div>' +
      '<div class="f-text" style="--catc:' + c.color + '">' +
        '<div class="cat"><span class="pin"></span>' + esc(c.label) + "</div>" +
        '<h1 class="f-title">' + esc(it.title) + "</h1>" +
        (it.summary ? '<p class="f-sum">' + esc(it.summary) + "</p>" : "") +
        '<div class="meta"><b>' + esc(it.source) + '</b><span class="sep">/</span>' + when + "</div>" +
      "</div>";
    var imgEl = el.querySelector(".f-img");

    function reveal() {
      el.classList.add("on");
      $(other).classList.remove("on");
      state.activeSlide = slideId === "fA" ? 0 : 1;
      var bar = $("fBar");
      bar.style.transition = "none"; bar.style.width = "0";
      void bar.offsetWidth;
      bar.style.transition = "width " + (CFG.featureEvery - 400) + "ms linear";
      bar.style.width = "100%";
    }
    if (it.img && !state.badImg[it.img]) {
      probe(it.img).then(function (ok) {
        if (ok) imgEl.style.backgroundImage = 'url("' + it.img.replace(/"/g, "%22") + '")';
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
    Object.keys(state.news.categories).forEach(function (k) {
      if (k === "curiosity") return;
      state.news.categories[k].slice(0, 8).forEach(function (x) { out.push(x); });
    });
    out.sort(function (a, b) { return new Date(b.ts) - new Date(a.ts); });
    return out.slice(0, 20);
  }
  function showLatest() {
    var items = allRecent().filter(function (x) { return x.id !== state.currentFeature; });
    if (!items.length) return;
    var per = 3, pages = Math.max(1, Math.ceil(items.length / per));
    var page = state.latestPage % pages; state.latestPage++;
    var slice = items.slice(page * per, page * per + per);
    var box = $("latestList");
    box.classList.add("fade");
    setTimeout(function () {
      box.innerHTML = slice.map(function (it) {
        var c = CATS[it.cat] || CATS.business;
        return '<div class="l-item" style="--catc:' + c.color + '"><div class="thumb"></div><div class="l-body">' +
          '<div class="l-cat">' + esc(c.label) + "</div>" +
          '<div class="l-title">' + esc(it.title) + "</div>" +
          '<div class="l-meta"><b>' + esc(it.source) + "</b> · " + ago(it.ts) + "</div></div></div>";
      }).join("");
      var thumbs = box.querySelectorAll(".thumb");
      slice.forEach(function (it, i) { fillImage(thumbs[i], it, true); });
      box.classList.remove("fade");
    }, 700);
  }

  /* ---------- Cards ---------- */
  function buildCards() {
    $("cards").innerHTML = CARD_SLOTS.map(function (s, i) {
      return '<div class="card" id="card' + i + '" style="--catc:' + CATS[s.cats[0]].color + '"><div class="inner"></div></div>';
    }).join("");
  }
  function showCard(i) {
    var slot = CARD_SLOTS[i];
    var cats = slot.cats.filter(function (c) { return list(c).length; });
    if (!cats.length) return;
    var cat = cats[state.cardPtr[i] % cats.length];
    state.cardPtr[i]++;
    var it = nextFrom(cat, false);
    if (!it) return;
    var c = CATS[cat];
    var card = $("card" + i), inner = card.querySelector(".inner");
    var head = cat === "recruise" ? (it.label || "Recruise Corner") : (cat === "curiosity" ? (it.year ? "On this day · " + it.year : "Did You Know?") : CATS[cat].label);
    var sub = cat === "curiosity" ? "Curiosity Corner" : (cat === "recruise" ? "Inside Recruise" : "");
    var meta = it.ts ? "<b>" + esc(it.source) + "</b> · " + ago(it.ts) : "<b>" + esc(it.source) + "</b>";
    if (it.year) meta = "<b>Wikipedia</b> · " + stamp(new Date().toISOString());
    inner.classList.add("fade");
    setTimeout(function () {
      card.style.setProperty("--catc", c.color);
      inner.innerHTML = '<div class="c-head"><div class="c-cat">' + esc(head) + "</div>" +
        (sub ? '<span class="c-sub">' + esc(sub) + "</span>" : "") + "</div>" +
        '<div class="c-row"><div class="c-thumb"></div><div class="c-title">' + esc(it.title) + "</div></div>" +
        '<div class="c-meta">' + meta + "</div>";
      fillImage(inner.querySelector(".c-thumb"), it, true);
      inner.classList.remove("fade");
    }, 800);
  }

  /* ---------- Ticker ---------- */
  var tick = { x: 0, w: 0, last: 0, pending: null };
  function tickerHTML() {
    var out = [];
    var order = ["gcc", "hiring", "business", "tech", "ta", "world", "startup", "gcc", "economy", "hiring", "tech", "business"];
    var used = {};
    for (var round = 0; round < 4; round++) {
      order.forEach(function (cat) {
        var arr = list(cat);
        for (var i = 0; i < arr.length; i++) {
          if (!used[arr[i].id]) { used[arr[i].id] = 1; out.push(arr[i]); break; }
        }
      });
    }
    return out.map(function (it) {
      var c = CATS[it.cat] || CATS.business;
      return '<span class="t-item" style="--catc:' + c.color + '"><span class="t-src">' + esc(it.source) + "</span>" + esc(it.title) + "</span>";
    }).join("");
  }
  function buildTicker() {
    var html = tickerHTML();
    if (!html) return;
    if (!tick.w) applyTicker(html); else tick.pending = html; // swap at the loop point, no jump
  }
  function applyTicker(html) {
    var t = $("tTrack");
    t.innerHTML = html + html;
    tick.w = t.scrollWidth / 2;
    tick.x = 0;
  }
  function runTicker(ts) {
    if (!tick.last) tick.last = ts;
    var dt = Math.min(100, ts - tick.last); tick.last = ts;
    if (tick.w) {
      tick.x += CFG.tickerSpeed * dt / 1000;
      if (tick.x >= tick.w) {
        if (tick.pending) { applyTicker(tick.pending); tick.pending = null; }
        else tick.x -= tick.w;
      }
      $("tTrack").style.transform = "translate3d(" + (-tick.x).toFixed(1) + "px,0,0)";
    }
    requestAnimationFrame(runTicker);
  }

  /* ---------- Start ---------- */
  var started = false;
  function start() {
    if (started || !state.news) {
      if (!state.news) setTimeout(function () { loadData(true); }, 30000);
      return;
    }
    started = true;
    showFeature();
    setInterval(showFeature, CFG.featureEvery);
    showLatest();
    setInterval(showLatest, CFG.latestEvery);
    CARD_SLOTS.forEach(function (_, i) {
      showCard(i);
      setTimeout(function () { setInterval(function () { showCard(i); }, CFG.cardEvery); }, i * 2600);
    });
  }

  function keepAwake() {
    try {
      if (navigator.wakeLock) navigator.wakeLock.request("screen").catch(function () {});
    } catch (e) {}
  }

  fit();
  window.addEventListener("resize", fit);
  tickClock();
  setInterval(tickClock, 1000);
  buildCards();
  requestAnimationFrame(runTicker);
  loadData(true);
  setInterval(function () { loadData(false); }, CFG.dataEvery);
  setInterval(updatedLabel, 60000);
  keepAwake();
  document.addEventListener("visibilitychange", function () { if (!document.hidden) keepAwake(); });
  document.addEventListener("dblclick", function () {
    var d = document.documentElement;
    if (!document.fullscreenElement && d.requestFullscreen) d.requestFullscreen().catch(function () {});
  });
  // Periodic clean reload keeps long-running TV browsers fresh; only when the site is reachable.
  setTimeout(function () {
    fetch("version.json?t=" + Date.now(), { cache: "no-store" }).then(function (r) { if (r.ok) location.reload(); }).catch(function () {});
  }, CFG.hardReloadEvery);
})();
