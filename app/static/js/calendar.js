(function () {
  var MEETINGS_URL = "meetings.json"; // path to your generated file
  var all = [];
  var $ = function (id) { return document.getElementById(id); };

  var isNone = function (v) { return v == null || String(v).trim().toLowerCase() === "none" || String(v).trim() === ""; };

  function parse(raw) {
    var out = [];
    (Array.isArray(raw) ? raw : []).forEach(function (m) {
      if (!m || isNone(m.club_name) || isNone(m.date) || isNone(m.start_time)) return;
      var d = String(m.date).split("-").map(Number);
      var s = String(m.start_time).split(":").map(Number); // handles "16:0" as well as "16:00"
      if (d.length !== 3 || s.length < 2 || d.some(isNaN) || s.some(isNaN)) return;
      var start = new Date(d[0], d[1] - 1, d[2], s[0], s[1]);
      var end = null;
      if (!isNone(m.end_time)) {
        var e = String(m.end_time).split(":").map(Number);
        if (e.length >= 2 && !e.some(isNaN)) end = new Date(d[0], d[1] - 1, d[2], e[0], e[1]);
      }
      if (isNaN(start)) return;
      out.push({
        name: String(m.club_name),
        subject: isNone(m.subject) ? "" : String(m.subject).replace(/\s+/g, " ").trim(),
        start: start,
        end: end || start
      });
    });
    out.sort(function (a, b) { return a.start - b.start || a.name.localeCompare(b.name); });
    return out;
  }

  var fmtTime = function (d) {
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  };
  var dayKey = function (d) { return d.getFullYear() + "-" + d.getMonth() + "-" + d.getDate(); };

  function relLabel(d) {
    var t = new Date(); t.setHours(0, 0, 0, 0);
    var x = new Date(d); x.setHours(0, 0, 0, 0);
    var diff = Math.round((x - t) / 864e5);
    if (diff === 0) return "Today";
    if (diff === 1) return "Tomorrow";
    return d.toLocaleDateString([], { weekday: "long" });
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function render() {
    var now = new Date();
    var term = $("q").value.trim().toLowerCase();
    var showPast = $("past").checked;
    var box = $("results");
    box.textContent = "";

    var shown = all.filter(function (m) {
      if (term && (m.name + " " + m.subject).toLowerCase().indexOf(term) === -1) return false;
      if (!showPast && m.end < now) return false;
      return true;
    });

    var upcoming = all.filter(function (m) { return m.end >= now; }).length;
    $("summary").textContent = all.length
      ? upcoming + " upcoming · " + (all.length - upcoming) + " past"
      : "No meetings found yet.";

    if (!shown.length) {
      var e = el("div", "empty");
      e.appendChild(el("strong", null, all.length ? "No meetings match." : "No meetings to show."));
      e.appendChild(document.createTextNode(
        all.length ? "Clear the search or turn on past meetings to see more." : "Check that meetings.json has entries with a club, date, and start time."));
      box.appendChild(e);
      return;
    }

    var groups = [], last = null;
    shown.forEach(function (m) {
      var k = dayKey(m.start);
      if (k !== last) { groups.push({ date: m.start, items: [] }); last = k; }
      groups[groups.length - 1].items.push(m);
    });

    groups.forEach(function (g) {
      var endOfDay = new Date(g.date); endOfDay.setHours(23, 59, 59, 999);
      var day = el("section", "day" + (endOfDay < now ? " is-past" : ""));
      var dt = el("div", "date");
      dt.appendChild(el("div", "num", String(g.date.getDate())));
      dt.appendChild(el("div", "mon", g.date.toLocaleDateString([], { month: "short", year: "numeric" })));
      dt.appendChild(el("span", "rel", relLabel(g.date)));
      day.appendChild(dt);

      var ul = el("ul", "list");
      g.items.forEach(function (m) {
        var past = m.end < now, live = m.start <= now && now <= m.end && m.end > m.start;
        var li = el("li", "meeting" + (past ? " past" : "") + (live ? " live" : ""));
        li.appendChild(el("span", "name", m.name));
        var t = el("span", "time", m.end > m.start ? fmtTime(m.start) + " – " + fmtTime(m.end) : fmtTime(m.start));
        if (live) { var tag = el("span", "live-tag", "Happening now  "); t.insertBefore(tag, t.firstChild); }
        li.appendChild(t);
        if (m.subject) li.appendChild(el("span", "subject", m.subject));
        ul.appendChild(li);
      });
      day.appendChild(ul);
      box.appendChild(day);
    });
  }

  function load(raw) { all = parse(raw); render(); }

  function showLoadError() {
    $("summary").textContent = "Could not load meetings. Please refresh and try again.";
  }

  function readFile(f) {
    var r = new FileReader();
    r.onload = function () {
      try { load(JSON.parse(r.result)); }
      catch (err) { $("summary").textContent = "That file isn't valid JSON."; }
    };
    r.readAsText(f);
  }

  $("q").addEventListener("input", render);
  $("past").addEventListener("change", render);
  window.addEventListener("dragover", function (e) { e.preventDefault(); document.body.classList.add("drop-active"); });
  window.addEventListener("dragleave", function () { document.body.classList.remove("drop-active"); });
  window.addEventListener("drop", function (e) {
    e.preventDefault(); document.body.classList.remove("drop-active");
    if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]);
  });
  setInterval(function () { if (all.length) render(); }, 60000); // keep "now" and past/upcoming fresh

  fetch(MEETINGS_URL, { cache: "no-store" })
    .then(function (r) { if (r.status === 401) { window.location.replace("/login"); throw new Error("Sign in required"); } if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(load)
    .catch(showLoadError);
})();
