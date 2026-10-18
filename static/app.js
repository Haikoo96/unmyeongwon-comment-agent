const $ = (s) => document.querySelector(s);
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new Error(body?.detail || r.statusText);
  return body;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https:\/\//.test(u || "") ? u : "#");

let current = null;   // 선택한 영상
let posting = null;   // 진행 중인 게시 {id, video_id}
let pollTimer = null;
let tick = null;

async function refreshStatus() {
  const s = await api("/api/status");
  const el = $("#today");
  el.textContent = `오늘 ${s.posted_today}/${s.daily_max} 게시`;
  el.classList.toggle("full", s.posted_today >= s.daily_max);
  const sel = $("#profile");
  if (!sel.options.length) sel.innerHTML = s.profiles.map((p) => `<option>${esc(p)}</option>`).join("");
}

function renderVideos(list) {
  $("#videoList").innerHTML = list.map((v) => `
    <li data-id="${esc(v.id)}" class="${v.posted ? "done" : ""} ${current?.id === v.id ? "sel" : ""}">
      <img src="${esc(safeUrl(v.thumbnail))}" alt="">
      <div><div class="t">${esc(v.title)}</div>
        <div class="sub">${esc(v.channel_title)} · ${esc(v.published_at?.slice(0, 10))}</div>
        ${v.posted ? '<span class="tag">✓ 게시함</span>' : ""}</div>
    </li>`).join("");
  $("#videoList").querySelectorAll("li").forEach((li) =>
    li.addEventListener("click", () => select(list.find((v) => v.id === li.dataset.id))));
}

async function loadList() { renderVideos(await api("/api/videos")); }

$("#loadBtn").addEventListener("click", async () => {
  const msg = $("#loadMsg"); msg.className = "msg"; msg.textContent = "불러오는 중…";
  try { const list = await api("/api/videos/load", { method: "POST" }); renderVideos(list); msg.textContent = `${list.length}개 영상`; }
  catch (e) { msg.className = "msg err"; msg.textContent = e.message; }
});

$("#linkForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#loadMsg"); msg.className = "msg"; msg.textContent = "확인하는 중…";
  try {
    const v = await api("/api/videos/link", { method: "POST", body: JSON.stringify({ url: $("#linkInput").value }) });
    $("#linkInput").value = ""; msg.textContent = ""; await loadList(); select(v);
  } catch (err) { msg.className = "msg err"; msg.textContent = err.message; }
});

async function select(v) {
  current = v;
  const vid = v.id;
  document.querySelectorAll("#videoList li").forEach((li) => li.classList.toggle("sel", li.dataset.id === vid));
  $("#col2").classList.remove("locked");
  $("#empty2").hidden = true; $("#detail").hidden = false;
  $("#dThumb").src = safeUrl(v.thumbnail); $("#dTitle").textContent = v.title; $("#dChannel").textContent = v.channel_title;
  $("#dLink").href = `https://www.youtube.com/watch?v=${encodeURIComponent(vid)}`;
  $("#analysis").hidden = true; $("#analyzing").hidden = true;
  $("#col3").classList.add("locked");
  renderPostPanel(lastPost?.video_id === vid ? lastPost : undefined);
  try {
    const a = await api(`/api/videos/${vid}/analysis`);
    if (current?.id !== vid) return;  // 그사이 다른 영상을 골랐으면 버려요
    a ? renderAnalysis(a) : run("analyze");
  } catch (e) { showWait(e.message, true); }
}

function showWait(text, err = false) {
  const el = $("#analyzing"); el.hidden = false; el.className = err ? "msg err" : "msg"; el.textContent = text;
}

// mode: analyze(에이전트 3개 전부) / rewrite(댓글 작가만)
async function run(mode) {
  const vid = current.id;
  const label = mode === "analyze"
    ? "에이전트 3개가 순서대로 일하는 중이에요 (페르소나 → 웹 검색·여정 → 댓글). 보통 1~3분 걸려요"
    : "같은 페르소나로 댓글만 다시 쓰는 중이에요. 보통 20~40초 걸려요";
  $("#analysis").hidden = true; $("#col3").classList.add("locked");
  const t0 = Date.now();
  clearInterval(tick);
  const update = () => showWait(`${label} · ${Math.round((Date.now() - t0) / 1000)}초`);
  update(); tick = setInterval(() => { if (current?.id === vid) update(); }, 1000);
  try {
    const a = await api(`/api/videos/${vid}/${mode}`, { method: "POST" });
    if (current?.id !== vid) return;
    renderAnalysis(a);
  } catch (e) { if (current?.id === vid) showWait(e.message, true); }
  finally { clearInterval(tick); }
}
$("#reBtn").addEventListener("click", () => run("rewrite"));
$("#reAllBtn").addEventListener("click", () => run("analyze"));

const J = [["trigger", "계기"], ["struggle", "몸부림"], ["now", "지금 상태"], ["unmet_need", "채워지지 않은 욕구"], ["bridge", "운명원 다리"]];

function renderAnalysis(a) {
  $("#analyzing").hidden = true; $("#analysis").hidden = false;
  $("#worry").textContent = a.worry;
  const src = $("#srcBadge");
  if (a.transcript_used === null || a.transcript_used === undefined) { src.textContent = ""; }
  else { src.textContent = a.transcript_used ? "자막 기반" : "자막 없음 · 제목·설명 기반"; src.className = a.transcript_used ? "badge" : "badge low"; }
  $("#pLabel").textContent = a.persona?.label || "";
  const conf = a.persona?.confidence;
  $("#confBadge").textContent = conf ? `근거 ${conf}` : "";
  $("#confBadge").className = conf === "낮음" ? "badge low" : "badge";
  const links = (a.journey?.sources || []).filter((u) => /^https?:\/\//.test(u));
  $("#journey").innerHTML = J.map(([k, l]) => `<div class="${k === "bridge" ? "bridge" : ""}"><span>${l}</span><span>${esc(a.journey?.[k])}</span></div>`).join("")
    + (links.length ? `<div><span>참고한 글</span><span>${links.map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noopener">${i + 1}</a>`).join(" · ")}</span></div>` : "");
  $("#evidence").innerHTML = (a.evidence || []).map((t) => `<li>${esc(t)}</li>`).join("") || "<li>없음</li>";
  $("#filtered").innerHTML = (a.filtered || []).map((f) => `<li>${esc(f.text)} <span class="sub">— ${esc(f.reason)}</span></li>`).join("") || "<li>없음</li>";
  $("#scene").textContent = a.scene || "";
  $("#draft").value = a.draft || "";
  renderChecks(a.checks);
}

function renderChecks(checks) {
  $("#checks").innerHTML = checks.map((c) => `<span class="chk ${c.ok ? "" : "no"}">${c.ok ? "✓" : "✕"} ${esc(c.rule)}${c.detail ? " · " + esc(c.detail) : ""}</span>`).join("");
  const ok = checks.every((c) => c.ok) && !current?.posted;
  $("#col3").classList.toggle("locked", !ok);
  $("#postBtn").disabled = !ok || !!posting;
  if (current?.posted) { $("#postMsg").className = "msg"; $("#postMsg").textContent = "이 영상에는 이미 댓글을 달았어요."; }
}

let checkTimer;
$("#draft").addEventListener("input", () => {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => renderChecks(await api("/api/check", { method: "POST", body: JSON.stringify({ text: $("#draft").value }) })), 200);
});

// ③ 진행 표시. 게시는 한 번에 하나만 돌고, 다른 영상을 보고 있어도 계속 추적해요.
const ORDER = ["opening", "typing", "submitted", "posted"];
let reached = -1;

let lastPost = null;

function renderPostPanel(p) {
  if (p) lastPost = p;
  const mine = p && current && p.video_id === current.id;
  document.querySelectorAll("#progress li").forEach((li) => li.classList.remove("on", "cur", "bad"));
  $("#fail").hidden = true; $("#unverified").hidden = true;
  $("#postMsg").textContent = ""; $("#postMsg").className = "msg";
  if (posting && !mine) { $("#postMsg").textContent = "다른 영상에 댓글을 게시하는 중이에요. 끝나면 이어서 할 수 있어요."; return; }
  if (!mine) return;

  const lis = [...document.querySelectorAll("#progress li")];
  const idx = ORDER.indexOf(p.status);
  if (idx >= 0) reached = Math.max(reached, idx);
  // 화면의 점 4개: 여는 중 / 입력 중 / 게시 완료 / 댓글 보기
  const dot = p.status === "posted" ? 3 : Math.min(reached, 1);
  lis.forEach((li, i) => {
    li.classList.toggle("on", i <= dot);
    li.classList.toggle("cur", i === dot && !["posted", "failed", "unverified"].includes(p.status));
  });
  if (p.status === "posted") $("#viewLink").href = safeUrl(p.comment_url) !== "#" ? p.comment_url : `https://www.youtube.com/watch?v=${encodeURIComponent(p.video_id)}`;
  if (p.status === "failed") {
    lis[Math.min(reached + 1, 2)]?.classList.add("bad");
    $("#fail").hidden = false;
    $("#fail").innerHTML = `<b>실패</b><span>${esc(p.error)}</span>${p.screenshot ? `<a href="/shots/${encodeURIComponent(p.screenshot)}" target="_blank"><img src="/shots/${encodeURIComponent(p.screenshot)}" alt="실패 화면"></a>` : ""}`;
  }
  if (p.status === "unverified") {
    lis[2].classList.add("bad");
    showUnverified(p);
  }
}

function showUnverified(p) {
  const box = $("#unverified"); box.hidden = false; box.dataset.id = p.id;
  $("#uvMsg").textContent = p.error || "";
  $("#uvLink").href = `https://www.youtube.com/watch?v=${encodeURIComponent(p.video_id)}`;
  const shot = $("#uvShot"); shot.hidden = !p.screenshot;
  if (p.screenshot) { shot.href = `/shots/${encodeURIComponent(p.screenshot)}`; shot.querySelector("img").src = shot.href; }
}

async function resolvePost(id, posted) {
  const p = await api(`/api/posts/${id}/resolve`, { method: "POST", body: JSON.stringify({ posted }) });
  if (current?.id === p.video_id) current.posted = posted ? 1 : 0;
  renderPostPanel(p); refreshStatus(); loadLog(); loadList();
  if (!posted && current?.id === p.video_id) renderChecks(await api("/api/check", { method: "POST", body: JSON.stringify({ text: $("#draft").value }) }));
}
$("#unverified").addEventListener("click", (e) => {
  const b = e.target.closest("[data-resolve]"); if (b) resolvePost($("#unverified").dataset.id, b.dataset.resolve === "1");
});

$("#postBtn").addEventListener("click", async () => {
  $("#postBtn").disabled = true;
  try {
    const { id } = await api("/api/posts", { method: "POST", body: JSON.stringify({ video_id: current.id, profile: $("#profile").value, text: $("#draft").value }) });
    posting = { id, video_id: current.id }; reached = -1;
    renderPostPanel({ id, video_id: current.id, status: "queued" });
    pollTimer = setInterval(async () => {
      const p = await api(`/api/posts/${id}`);
      renderPostPanel(p);
      if (["posted", "failed", "unverified"].includes(p.status)) {
        clearInterval(pollTimer); posting = null;
        if (current?.id === p.video_id && p.status !== "failed") current.posted = 1;
        refreshStatus(); loadLog(); loadList();
        if (current?.id === p.video_id) $("#postBtn").disabled = p.status !== "failed";
        renderPostPanel(p);
      }
    }, 1000);
  } catch (e) { $("#postMsg").className = "msg err"; $("#postMsg").textContent = e.message; $("#postBtn").disabled = false; }
});

const STATUS = { posted: "✓ 성공", failed: "✕ 실패", unverified: "? 확인 필요", queued: "대기", opening: "여는 중", typing: "입력 중", submitted: "확인 중" };

async function loadLog() {
  const rows = await api("/api/posts");
  $("#logBody").innerHTML = rows.map((p) => `<tr>
    <td class="time">${esc(p.created_at)}</td>
    <td>${esc(p.channel_title)}<div class="sub">${esc(p.title)}</div></td>
    <td>${esc(p.profile)}</td><td>${esc(p.text)}</td>
    <td><span class="st ${esc(p.status)}">${STATUS[p.status] || esc(p.status)}</span>
      ${p.error ? `<div class="sub">${esc(p.error)}</div>` : ""}
      ${p.screenshot ? `<a href="/shots/${encodeURIComponent(p.screenshot)}" target="_blank">캡처</a>` : ""}
      ${p.comment_url ? ` · <a href="${esc(safeUrl(p.comment_url))}" target="_blank" rel="noopener">댓글</a>` : ""}
      ${p.status === "unverified" ? `<div class="resolve"><button data-id="${p.id}" data-ok="1">올라갔어요</button><button data-id="${p.id}" data-ok="0">안 올라갔어요</button></div>` : ""}</td></tr>`).join("")
    || '<tr><td colspan="5" class="sub">아직 기록이 없어요.</td></tr>';
}
$("#logBody").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-id]"); if (b) resolvePost(b.dataset.id, b.dataset.ok === "1");
});

refreshStatus(); loadList(); loadLog();
