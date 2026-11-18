"""(v6.3) Small local website around crawler/fifa_crawl.py: type the competition, the year and two teams, wait while it
crawls, then read every metadata CSV of the match in the browser (tabs + filter) and download them (.csv / .zip).

Standard library only (no Flask). Listens on 127.0.0.1, so only this computer can open it.

usage:
    python -m crawler.crawl_web                 # then open http://127.0.0.1:8765
    python -m crawler.crawl_web --port 9000 --out metadata/fifa --open
"""
import argparse
import csv
import io
import json
import os
import sys
import threading
import traceback
import uuid
import webbrowser
import zipfile
from argparse import Namespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from crawler import fifa_crawl as fc
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root (this file is in crawler/)
# tab order in the page; all_metadata.csv = every other file in one long table
FILES = ["all_metadata", "match_info", "teams", "lineups", "staff", "goals", "events", "standings_before",
         "form", "head_to_head", "facts"]
SEARCHES, JOBS, LOCK = {}, {}, threading.Lock()
OPTS = Namespace(out=os.path.join(HERE, "metadata", "fifa"))


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    return (rows[0], rows[1:]) if rows else ([], [])


def search(body):
    gender = {"men": False, "women": True}.get(body.get("gender"), None)
    a, b, matches = fc.find_matches(body.get("year", "").strip(), body.get("team_a", "").strip(),
                                    body.get("team_b", "").strip(), body.get("competition", "").strip() or None, gender)
    sid = uuid.uuid4().hex[:12]
    with LOCK:
        SEARCHES[sid] = matches
    return {"search_id": sid, "team_a": a["name"], "team_b": b["name"],
            "matches": [{"index": i, "label": fc.match_label(m), "date": m["Date"][:10],
                         "competition": fc.txt(m["CompetitionName"]), "season": fc.txt(m["SeasonName"]),
                         "home": fc.team_name(m["Home"]), "away": fc.team_name(m["Away"]),
                         "score": f"{m.get('HomeTeamScore')} - {m.get('AwayTeamScore')}"} for i, m in enumerate(matches)]}


def run_job(jid, match, profiles):
    job = JOBS[jid]

    def log(msg):
        job["log"].append(str(msg))
    try:
        log(f"Crawl {fc.match_label(match)}")
        args = Namespace(out=OPTS.out, form=5, h2h_years=10, profiles=profiles)
        job["out"] = fc.crawl_match(match, args, log=log)
        job["status"] = "done"
        log("Xong.")
    except Exception as e:  # shown in the page
        job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"
        log(traceback.format_exc(limit=3))


def start(body):
    with LOCK:
        matches = SEARCHES.get(body.get("search_id"))
    if matches is None:
        raise fc.CrawlError("Kết quả tìm kiếm đã hết hạn, hãy tìm lại.")
    match = matches[int(body.get("index", 0))]
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"status": "running", "log": [], "error": "", "out": ""}
    threading.Thread(target=run_job, args=(jid, match, bool(body.get("profiles", True))), daemon=True).start()
    return {"job_id": jid}


def job_state(jid):
    job = JOBS.get(jid)
    if job is None:
        raise fc.CrawlError("Không có job này.")
    res = {"status": job["status"], "log": job["log"], "error": job["error"]}
    if job["status"] == "done":
        try:
            res["folder"] = os.path.relpath(job["out"], HERE)
        except ValueError:  # another drive on Windows
            res["folder"] = job["out"]
        res["files"] = []
        for name in FILES:
            path = os.path.join(job["out"], f"{name}.csv")
            if os.path.exists(path):
                header, rows = read_csv(path)
                res["files"].append({"name": name, "header": header, "rows": rows})
    return res


def job_file(jid, name):
    """-> (bytes, content type, download name) of one CSV or of all of them zipped."""
    job = JOBS.get(jid)
    if job is None or job["status"] != "done":
        return None
    folder = job["out"]
    base = os.path.basename(folder)
    if name == "all.zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for n in FILES:
                p = os.path.join(folder, f"{n}.csv")
                if os.path.exists(p):
                    z.write(p, f"{base}/{n}.csv")
        return buf.getvalue(), "application/zip", f"{base}.zip"
    if name.endswith(".csv") and name[:-4] in FILES and os.path.exists(os.path.join(folder, name)):
        with open(os.path.join(folder, name), "rb") as f:
            return f.read(), "text/csv; charset=utf-8", f"{base} - {name}"
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):  # keep the terminal quiet
        pass

    def send(self, code, data, ctype="application/json; charset=utf-8", filename=None):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" +
                             "".join(c if c.isalnum() or c in "-_.() " else "_" for c in filename).replace(" ", "%20"))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path in ("/", "/index.html"):
            return self.send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        parts = path.strip("/").split("/")
        try:
            if len(parts) == 3 and parts[:2] == ["api", "job"]:
                return self.send(200, job_state(parts[2]))
            if len(parts) == 3 and parts[0] == "files":
                got = job_file(parts[1], parts[2])
                if got:
                    return self.send(200, got[0], got[1], filename=got[2])
        except fc.CrawlError as e:
            return self.send(400, {"error": str(e)})
        except Exception as e:
            return self.send(500, {"error": f"{type(e).__name__}: {e}"})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if self.path == "/api/search":
                return self.send(200, search(body))
            if self.path == "/api/crawl":
                return self.send(200, start(body))
            self.send(404, {"error": "not found"})
        except fc.CrawlError as e:  # first line = message; the page shows the suggestions as buttons
            self.send(400, {"error": str(e).split("\n")[0], "suggestions": e.suggestions})
        except Exception as e:
            self.send(500, {"error": f"{type(e).__name__}: {e}"})


PAGE = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crawl metadata trận đấu</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2129;--muted:#5f6673;--line:#dfe3ea;--accent:#1f6feb;--accent-text:#fff;
--err-bg:#fdecec;--err:#b42318;--ok:#1a7f37;--row:#f3f5f8;--chip:#eef2f8}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--text:#e6e8eb;--muted:#9aa3b0;--line:#2b303a;
--accent:#4c8dff;--accent-text:#0b0d10;--err-bg:#3a1d1d;--err:#ff8a80;--ok:#56d364;--row:#1d2128;--chip:#222833}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}
p.sub{margin:0 0 20px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
form{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;align-items:end}
label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--muted)}
input,select{font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.check{flex-direction:row;align-items:center;gap:8px}
button{font:inherit;font-weight:600;border:0;border-radius:8px;padding:9px 16px;background:var(--accent);color:var(--accent-text);cursor:pointer}
button:disabled{opacity:.5;cursor:default}
button.ghost{background:var(--chip);color:var(--text)}
.err{background:var(--err-bg);color:var(--err);border-radius:8px;padding:10px 12px;margin-top:12px;white-space:pre-wrap}
.spin{display:inline-block;width:16px;height:16px;border:2px solid var(--line);border-top-color:var(--accent);border-radius:50%;
animation:r .8s linear infinite;vertical-align:-3px;margin-right:8px}
@keyframes r{to{transform:rotate(360deg)}}
pre.log{max-height:180px;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;
font-size:12.5px;margin:10px 0 0;white-space:pre-wrap}
.match{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--line)}
.match:first-of-type{border-top:0}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}
.tab{background:var(--chip);color:var(--text);font-weight:500;padding:6px 10px;font-size:13.5px}
.tab.on{background:var(--accent);color:var(--accent-text)}
.tab small{opacity:.7;margin-left:4px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between}
.bar a{color:var(--accent);font-weight:600;text-decoration:none;margin-right:12px}
.wrap{overflow:auto;max-height:70vh;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;font-size:13px;width:max-content;min-width:100%}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;max-width:520px}
th{position:sticky;top:0;background:var(--card);z-index:1}
tr:nth-child(even) td{background:var(--row)}
.muted{color:var(--muted);font-size:13px}
.ok{color:var(--ok);font-weight:600}
</style>
</head>
<body>
<main>
<h1>Crawl metadata trận đấu</h1>
<p class="sub">Nguồn: API công khai của FIFA (api.fifa.com). Kết quả được lưu vào thư mục metadata của dự án.</p>

<div class="card">
<form id="f">
  <label>Mùa giải (tên giải, có thể để trống)<input name="competition" placeholder="vd: Women's Super League, Premier League"></label>
  <label>Năm tổ chức<input name="year" required placeholder="vd: 2025 hoặc 2025/2026"></label>
  <label>Đội bóng 1<input name="team_a" required placeholder="vd: Chelsea"></label>
  <label>Đội bóng 2<input name="team_b" required placeholder="vd: Manchester City"></label>
  <label>Đội nam / nữ<select name="gender"><option value="auto">Tự động (thử nam rồi nữ)</option>
    <option value="men">Nam</option><option value="women">Nữ</option></select></label>
  <label class="check"><input type="checkbox" name="profiles" checked> Lấy hồ sơ cầu thủ, HLV, đội</label>
  <button id="go" type="submit">Tìm trận</button>
</form>
<div id="msg"></div>
</div>

<div id="pick" class="card" hidden></div>
<div id="run" class="card" hidden></div>
<div id="out" class="card" hidden></div>
</main>
<script>
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const DESC = {all_metadata:"Tất cả trong một bảng", match_info:"Thông tin trận", teams:"Đội", lineups:"Đội hình + hồ sơ",
  staff:"HLV, trọng tài", goals:"Bàn thắng", events:"Diễn biến", standings_before:"BXH trước trận", form:"Phong độ",
  head_to_head:"Đối đầu", facts:"Câu bình luận"};
let state = {};

async function api(path, body){
  const r = await fetch(path, body ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)} : {});
  const j = await r.json();
  if (!r.ok) throw Object.assign(new Error(j.error || r.statusText), {suggestions: j.suggestions || []});
  return j;
}
function suggest(list){
  if (!list || !list.length) return "";
  return `<p class="muted" style="margin:12px 0 4px">Các trận gần đó của hai đội (bấm để tìm lại với năm đó):</p>` +
    list.map((s,i) => `<div class="match"><span>${esc(s.label)}</span><button class="ghost sug" data-i="${i}">Năm ${esc(s.year)}</button></div>`).join("");
}
function bindSuggest(list){
  document.querySelectorAll("button.sug").forEach(b => b.onclick = () => {
    const s = list[+b.dataset.i], f = $("#f");
    f.year.value = s.year; f.competition.value = s.competition;
    f.requestSubmit();
  });
}
function busy(el, text){ el.hidden = false; el.innerHTML = `<span class="spin"></span>${esc(text)}`; }

$("#f").addEventListener("submit", async e => {
  e.preventDefault();
  const fd = new FormData(e.target), body = Object.fromEntries(fd);
  body.profiles = fd.get("profiles") === "on";
  state.profiles = body.profiles;
  ["#pick","#run","#out"].forEach(s => $(s).hidden = true);
  $("#go").disabled = true;
  busy($("#msg"), "Đang tìm đội và lịch thi đấu trên FIFA...");
  try {
    const res = await api("/api/search", body);
    $("#msg").innerHTML = `<p class="muted">Đội 1: <b>${esc(res.team_a)}</b> · Đội 2: <b>${esc(res.team_b)}</b> · ${res.matches.length} trận</p>`;
    if (res.matches.length === 1) return crawl(res.search_id, 0, res.matches[0].label);
    $("#pick").hidden = false;
    $("#pick").innerHTML = "<b>Chọn trận cần crawl</b>" + res.matches.map(m =>
      `<div class="match"><span>${esc(m.date)} · ${esc(m.competition)}<br><b>${esc(m.home)} ${esc(m.score)} ${esc(m.away)}</b></span>
       <button class="ghost" data-i="${m.index}" data-l="${esc(m.label)}">Crawl</button></div>`).join("");
    $("#pick").querySelectorAll("button").forEach(b => b.onclick = () => crawl(res.search_id, +b.dataset.i, b.dataset.l));
  } catch (err) {
    $("#msg").innerHTML = `<div class="err">${esc(err.message)}</div>` + suggest(err.suggestions);
    bindSuggest(err.suggestions);
  } finally { $("#go").disabled = false; }
});

async function crawl(sid, index, label){
  $("#out").hidden = true;
  const run = $("#run"); run.hidden = false;
  run.innerHTML = `<div><span class="spin"></span>Đang crawl <b>${esc(label)}</b>... (khoảng 30–90 giây)</div><pre class="log" id="log"></pre>`;
  try {
    const {job_id} = await api("/api/crawl", {search_id:sid, index, profiles:state.profiles});
    for (;;) {
      await new Promise(r => setTimeout(r, 1500));
      const j = await api(`/api/job/${job_id}`);
      const log = $("#log"); log.textContent = j.log.join("\n"); log.scrollTop = log.scrollHeight;
      if (j.status === "error") throw new Error(j.error);
      if (j.status === "done") {
        run.innerHTML = `<span class="ok">Đã crawl xong.</span> <span class="muted">Lưu tại ${esc(j.folder)}</span>
          <pre class="log">${esc(j.log.join("\n"))}</pre>`;
        return show(job_id, j.files);
      }
    }
  } catch (err) { run.innerHTML += `<div class="err">${esc(err.message)}</div>`; run.querySelector(".spin")?.remove(); }
}

function show(jid, files){
  state.files = files; state.jid = jid;
  const out = $("#out"); out.hidden = false;
  out.innerHTML = `<div class="bar"><b>Các file CSV</b><span><a href="/files/${jid}/all.zip">Tải tất cả (.zip)</a></span></div>
    <div class="tabs">${files.map((f,i) => `<button class="tab" data-i="${i}" title="${esc(f.name)}.csv">${esc(DESC[f.name]||f.name)}<small>${f.rows.length}</small></button>`).join("")}</div>
    <div class="bar"><span id="meta" class="muted"></span><input id="q" placeholder="Lọc dòng..." style="min-width:220px"></div>
    <div class="wrap" style="margin-top:8px"><table id="t"></table></div>`;
  out.querySelectorAll(".tab").forEach(b => b.onclick = () => tab(+b.dataset.i));
  $("#q").oninput = () => render();
  tab(0);
}
function tab(i){
  state.cur = i; $("#q").value = "";
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("on", +b.dataset.i === i));
  render();
}
function render(){
  const f = state.files[state.cur], q = $("#q").value.trim().toLowerCase();
  const rows = q ? f.rows.filter(r => r.join(" ").toLowerCase().includes(q)) : f.rows;
  const shown = rows.slice(0, 2000);
  $("#meta").innerHTML = `<a href="/files/${state.jid}/${f.name}.csv">${esc(f.name)}.csv</a> · ${rows.length} dòng × ${f.header.length} cột` +
    (rows.length > shown.length ? ` (hiện 2000 dòng đầu, tải file để xem đủ)` : "");
  $("#t").innerHTML = `<thead><tr>${f.header.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>` +
    shown.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join("")}</tr>`).join("") + "</tbody>";
}
</script>
</body>
</html>
"""


def main():
    p = argparse.ArgumentParser(description="Website nhỏ để crawl metadata trận đấu từ FIFA")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--out", default=OPTS.out, help="thư mục lưu kết quả (mặc định metadata/fifa)")
    p.add_argument("--open", action="store_true", help="tự mở trình duyệt")
    a = p.parse_args()
    for stream in (sys.stdout, sys.stderr):  # Windows consoles (cp1252) cannot print Vietnamese otherwise
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    OPTS.out = os.path.abspath(a.out)
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}"
    print(f"Mở {url} trong trình duyệt (Ctrl+C để dừng). Kết quả lưu ở {OPTS.out}")
    if a.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
