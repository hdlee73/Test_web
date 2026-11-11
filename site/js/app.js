// 커뮤니티 금융 트렌드: 정적 JSON(data/*.json)만 읽는 단독 웹 화면.
// 모든 글자는 textContent 로만 넣고, 링크는 http(s)만 허용한다(수집 데이터는 외부 입력이므로).
import { dayFiles, loadMeta, loadPosts, loadTrends } from "./data.js";
import { BOARD_COLORS, fmtDateTime, h, safeUrl, sparkline, store, compact, setChildren } from "./ui.js";

export const APP_NAME = "커뮤니티 금융 트렌드";
export const APP_VERSION = "0.1.0";
const REPO = "hdlee73/Test_web";

const MENU = [
  ["home", "대시보드"],
  ["trend", "키워드 순위"],
  ["heat", "게시판별 히트맵"],
  ["spikes", "급상승"],
  ["posts", "게시물 검색"],
  ["watch", "관심 키워드"],
  ["boards", "게시판 상태"],
  ["info", "정보"],
];
const WINDOWS = [["today", "오늘"], ["3d", "최근 3일"], ["5d", "최근 5일"]];
const WINDOW_DAYS = { today: 1, "3d": 3, "5d": 5 };

const $ = (id) => document.getElementById(id);
const content = $("content");
let ctx = { meta: null, trends: null, error: null };

// ── 주소(#/화면?키=값)
function route() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  const id = MENU.some((m) => m[0] === path) ? path : "home";
  return { id, params: Object.fromEntries(new URLSearchParams(qs || "")) };
}
export function go(id, params = {}) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== "")).toString();
  const next = `#/${id}${qs ? "?" + qs : ""}`;
  if (next === location.hash) render();
  else location.hash = next;
}

// ── 메뉴
function renderMenu(active) {
  // 왼쪽 패널에는 이 도구 한 줄만 둔다(FSS Insights 통합 시 같은 모양). 하위 화면은 상단 탭.
  $("side").replaceChildren(
    h("div", { class: "brand" }, h("img", { src: "icon.svg", alt: "" }), APP_NAME),
    h("button", { class: "mi on", type: "button", "aria-current": "page", onclick: () => { document.body.classList.remove("open"); go("home"); } }, APP_NAME),
    h("div", { class: "foot" }, `v${APP_VERSION}`),
  );
  setChildren($("tabs"), MENU.map(([id, label]) =>
    h("button", { class: "tab" + (id === active ? " on" : ""), type: "button", role: "tab", "aria-selected": id === active ? "true" : "false", onclick: () => go(id) },
      label, id === "spikes" && ctx.trends?.spikes?.length ? h("span", { class: "badge" }, ctx.trends.spikes.length) : null)));
  $("tabs").querySelector(".on")?.scrollIntoView({ block: "nearest", inline: "center" });
}

// ── 화면 공통
const sourceName = (id) => {
  const s = ctx.meta?.sources.find((x) => x.id === id);
  return s ? `${s.site} ${s.board}` : id;
};
const sourceShort = (id) => ctx.meta?.sources.find((x) => x.id === id)?.site ?? id;
const sourceLabel = (id) => { const s = ctx.meta?.sources.find((x) => x.id === id); return s ? `${s.site} ${s.board}` : id; };
function sourceColor(id) {
  const i = ctx.meta.sources.filter((s) => s.enabled).findIndex((s) => s.id === id);
  return BOARD_COLORS[(i < 0 ? 0 : i) % BOARD_COLORS.length];
}
function segmented(selected, onPick) {
  return h("div", { class: "seg", role: "group", "aria-label": "기간" },
    WINDOWS.map(([id, label]) => h("button", { type: "button", "aria-pressed": String(id === selected), onclick: () => onPick(id) }, label)));
}
function postRow(p, query) {
  const url = safeUrl(p.u);
  const title = query ? highlight(p.t, query) : p.t;
  return h("div", { class: "post" },
    h("span", { class: "chip" }, sourceShort(p.s)),
    url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, title) : h("span", null, title),
    h("time", { datetime: p.at, title: p.x ? "게시 시각" : "수집 시각(사이트가 시각을 주지 않음)" }, (p.x ? "" : "≈") + fmtDateTime(p.at)));
}
function highlight(text, query) {
  const q = query.trim();
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return text;
  return [text.slice(0, i), h("mark", null, text.slice(i, i + q.length)), text.slice(i + q.length)];
}
const stateBox = (text, extra) => h("div", { class: "state" }, text, extra);

// ── 트렌드
function viewTrend(params) {
  const w = WINDOWS.some((x) => x[0] === params.w) ? params.w : "today";
  const cat = params.c || "";
  const win = ctx.trends.windows[w];
  const cats = [...new Set(win.keywords.map((k) => k.category))].sort();
  const rows = win.keywords.filter((k) => !cat || k.category === cat).slice(0, 40);
  const okBoards = ctx.meta.sources.filter((s) => s.enabled && (s.status === "ok" || s.status === "empty")).length;
  const enabled = ctx.meta.sources.filter((s) => s.enabled && s.status !== "no_key").length;
  const share = win.total_posts ? Math.round((win.finance_posts / win.total_posts) * 100) : 0;
  const boardIds = [...new Set(rows.flatMap((k) => Object.keys(k.sources)))];

  return h("div", { class: "wrap" },
    h("div", { class: "kpis" },
      kpi(win.total_posts.toLocaleString("ko-KR"), "수집한 글"),
      kpi(share + "%", "금융 관련 글 비중"),
      kpi(`${okBoards}/${enabled}`, "정상 게시판"),
      kpi(String(ctx.trends.spikes.length), "급상승 키워드")),
    h("div", { class: "row" },
      segmented(w, (id) => go("trend", { w: id, c: cat })),
      h("span", { class: "small muted" }, `한국시간 기준 · ${fmtDateTime(win.from)} 이후 · 글 하나에 여러 번 나와도 1건으로 셉니다`)),
    h("div", { class: "cats", role: "group", "aria-label": "분류" },
      [["", "전체"], ...cats.map((c) => [c, c])].map(([id, label]) =>
        h("button", { type: "button", "aria-pressed": String(id === cat), onclick: () => go("trend", { w, c: id }) }, label))),
    rows.length === 0
      ? stateBox("이 기간에는 집계된 키워드가 없습니다.")
      : h("div", { class: "card" },
          h("div", { class: "tablewrap" }, h("table", null,
            h("thead", null, h("tr", null, h("th", null, "#"), h("th", null, "키워드"), h("th", { class: "n" }, "글 수"), h("th", null, "게시판 비중"))),
            h("tbody", null, rows.map((k, i) => {
              const total = Object.values(k.sources).reduce((a, b) => a + b, 0) || 1;
              const open = () => go("posts", { k: k.keyword, w });
              return h("tr", { class: "k", tabindex: "0", role: "link", "aria-label": `${k.keyword} 게시물 보기`, onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
                h("td", null, i + 1),
                h("td", null, h("b", null, k.keyword), " ", h("span", { class: "chip" }, k.category)),
                h("td", { class: "n" }, k.posts),
                h("td", null, h("div", { class: "stack", title: Object.entries(k.sources).map(([s, c]) => `${sourceShort(s)} ${c}`).join(" · ") },
                  Object.entries(k.sources).map(([s, c]) => h("i", { style: { width: (c / total) * 100 + "%", background: sourceColor(s) } })))));
            })))),
          h("div", { class: "legend", style: { marginTop: "10px" } },
            boardIds.map((s) => h("span", null, h("i", { style: { background: sourceColor(s) } }), sourceShort(s))))),
    notice());
}
const kpi = (v, l) => h("div", { class: "kpi" }, h("b", null, v), h("span", null, l));
const notice = () => h("p", { class: "notice" }, ctx.meta.notice);

// ── 대시보드(첫 화면): 수집 현황 + 오늘 순위 + 관심 키워드 새 글 + 급상승
async function viewHome() {
  const win = ctx.trends.windows.today;
  const okBoards = ctx.meta.sources.filter((s) => s.enabled && (s.status === "ok" || s.status === "empty")).length;
  const enabled = ctx.meta.sources.filter((s) => s.enabled && s.status !== "no_key").length;
  const share = win.total_posts ? Math.round((win.finance_posts / win.total_posts) * 100) : 0;
  const top = win.keywords.slice(0, 8);
  const max = top[0]?.posts || 1;
  const watchBox = h("div", { class: "card" }, h("h2", null, "내 관심 키워드 새 글(오늘)"), h("p", { class: "small muted" }, "불러오는 중…"));
  const box = h("div", { class: "wrap" },
    h("div", { class: "kpis" },
      kpi(win.total_posts.toLocaleString("ko-KR"), "오늘 수집 글"),
      kpi(share + "%", "금융 관련 글 비중"),
      kpi(`${okBoards}/${enabled}`, "정상 게시판"),
      kpi(String(ctx.trends.spikes.length), "급상승 키워드")),
    h("div", { class: "two" },
      h("div", { class: "card" }, h("h2", null, "오늘 순위"),
        top.length === 0 ? h("p", { class: "small muted" }, "아직 집계된 키워드가 없습니다.") : top.map((k, i) =>
          h("div", { class: "hrow", tabindex: "0", role: "link", "aria-label": `${k.keyword} 게시물 보기`, onclick: () => go("posts", { k: k.keyword, w: "today" }), onkeydown: (e) => { if (e.key === "Enter") go("posts", { k: k.keyword, w: "today" }); } },
            h("span", { class: "rk" }, i + 1), h("span", { class: "nm" }, k.keyword),
            h("span", { class: "bar" }, h("i", { style: { width: (k.posts / max) * 100 + "%" } })),
            h("span", { class: "num" }, k.posts))),
        h("div", { style: { marginTop: "8px" } }, h("button", { class: "btn ghost sm", type: "button", onclick: () => go("trend") }, "전체 순위(오늘·3일·5일)"), " ",
          h("button", { class: "btn ghost sm", type: "button", onclick: () => go("heat") }, "게시판별 히트맵"))),
      watchBox),
    h("div", { class: "card" }, h("h2", null, "급상승"),
      ctx.trends.spikes.length === 0 ? h("p", { class: "small muted" }, "지금은 급상승 키워드가 없습니다. 데이터가 며칠 쌓이면 표시됩니다.")
        : h("div", { class: "row" }, ctx.trends.spikes.slice(0, 8).map((sp) =>
            h("button", { class: "chip " + (sp.new ? "warm" : "acc"), type: "button", style: { border: 0, cursor: "pointer" }, onclick: () => go("posts", { k: sp.keyword, w: "today" }) }, `${sp.keyword} ${sp.new ? "NEW" : "×" + sp.ratio}`)))),
    notice());
  const mine = renderSeq;
  const list = loadWatch();
  if (list.length === 0) {
    setChildren(watchBox, h("h2", null, "내 관심 키워드 새 글(오늘)"), h("p", { class: "small muted" }, "등록한 관심 키워드가 없습니다."),
      h("div", { style: { marginTop: "8px" } }, h("button", { class: "btn sm", type: "button", onclick: () => go("watch") }, "관심 키워드 등록")));
    return box;
  }
  const posts = (await loadPosts(ctx.meta, 1)).filter((p) => p.at >= win.from).sort((a, b) => (a.at < b.at ? 1 : -1));
  if (mine !== renderSeq) return box;
  setChildren(watchBox, h("h2", null, "내 관심 키워드 새 글(오늘)"), ...list.slice(0, 6).map((item) => {
    const hits = posts.filter((p) => matchesWatch(item, p));
    return h("div", { class: "witem" },
      h("div", { class: "row" }, h("b", null, item.k), h("span", { class: "chip " + (hits.length ? "warm" : "") }, `새 글 ${hits.length}`)),
      hits[0] ? postRow(hits[0]) : null);
  }), h("div", { style: { marginTop: "6px" } }, h("button", { class: "btn ghost sm", type: "button", onclick: () => go("watch") }, "관심 키워드 관리")));
  return box;
}

// ── 게시판별 히트맵(키워드 × 게시판, 글 천 건당 언급)
function viewHeat(params) {
  const w = WINDOWS.some((x) => x[0] === params.w) ? params.w : "3d";
  const win = ctx.trends.windows[w];
  const boards = Object.entries(win.by_source).filter(([, n]) => n > 0).slice(0, 12).map(([id]) => id);
  const rows = win.keywords.slice(0, 14);
  const per = (k, b) => ((k.sources[b] || 0) / win.by_source[b]) * 1000;
  const peak = Math.max(1, ...rows.flatMap((k) => boards.map((b) => per(k, b))));
  const grid = h("div", { class: "heat", style: { gridTemplateColumns: `104px repeat(${boards.length}, minmax(48px, 1fr))` } },
    h("div"), boards.map((b) => h("div", { class: "h" }, sourceLabel(b))),
    rows.map((k) => [
      h("div", { class: "hk" }, k.keyword),
      boards.map((b) => {
        const v = per(k, b), lv = v === 0 ? 0 : Math.min(4, 1 + Math.floor((v / peak) * 3.999));
        return h("div", { class: "c", style: { background: `var(--h${lv})`, color: lv >= 3 ? "#fff" : "inherit", fontWeight: lv >= 3 ? "600" : "400", cursor: k.sources[b] ? "pointer" : "default" },
          title: `${sourceName(b)} · ${k.keyword}: ${k.sources[b] || 0}건`, onclick: () => k.sources[b] && go("posts", { k: k.keyword, w, b }) }, v ? Math.round(v) : "");
      })]));
  return h("div", { class: "wrap" },
    h("div", { class: "row" }, segmented(w, (id) => go("heat", { w: id })), h("span", { class: "small muted" }, "숫자 = 그 게시판 글 천 건당 언급 수 · 칸을 누르면 게시물 목록")),
    rows.length === 0 ? stateBox("이 기간에는 집계된 키워드가 없습니다.") : h("div", { class: "card tablewrap" }, grid),
    h("div", { class: "legend" }, h("span", null, "적음"), [0, 1, 2, 3, 4].map((l) => h("span", null, h("i", { style: { background: `var(--h${l})` } }))), h("span", null, "많음")),
    notice());
}

// ── 급상승
function viewSpikes() {
  const list = ctx.trends.spikes;
  return h("div", { class: "wrap" },
    h("p", { class: "muted" }, "최근 24시간 언급량이 직전 4일 하루 평균보다 크게 늘어난 키워드입니다(24시간 3건 이상, 2배 이상)."),
    list.length === 0
      ? stateBox("지금은 급상승 키워드가 없습니다. 데이터가 며칠 쌓이면 표시됩니다.")
      : h("div", { class: "card" }, list.map((s) =>
          h("div", { class: "spike" },
            h("div", { class: "top2" },
              h("b", null, s.keyword), s.new ? h("span", { class: "chip warm" }, "처음 등장") : null,
              h("span", { class: "ratio" }, s.new ? `${s.recent_24h}건` : `×${s.ratio}`)),
            h("div", { class: "small muted" }, `최근 24시간 ${s.recent_24h}건 · 평소 하루 ${s.baseline_daily_avg}건`),
            h("div", null, h("button", { class: "btn ghost sm", type: "button", onclick: () => go("posts", { k: s.keyword, w: "today" }) }, "게시물 보기"))))),
    notice());
}

// ── 게시물 검색 / 키워드별 목록
async function viewPosts(params) {
  const w = WINDOWS.some((x) => x[0] === params.w) ? params.w : "5d";
  const k = params.k || "";
  const q = params.q || "";
  const board = params.b || "";
  const box = h("div", { class: "wrap" });
  const form = h("form", { class: "field", onsubmit: (e) => { e.preventDefault(); go("posts", { w, k: "", q: $("q").value.trim(), b: board }); } },
    h("input", { id: "q", type: "search", placeholder: "제목에서 검색 (예: 파킹통장)", value: q, "aria-label": "제목 검색" }),
    h("button", { class: "btn", type: "submit" }, "검색"));
  const boardSel = h("select", { "aria-label": "게시판", class: "ib", style: { width: "auto", padding: "0 8px" }, onchange: (e) => go("posts", { w, k, q, b: e.target.value }) },
    h("option", { value: "" }, "모든 게시판"),
    ...ctx.meta.sources.filter((s) => s.enabled).map((s) => h("option", { value: s.id, selected: s.id === board }, `${s.site} ${s.board}`)));
  box.append(h("div", { class: "row" }, segmented(w, (id) => go("posts", { w: id, k, q, b: board })), boardSel), form);
  if (k) box.append(h("div", { class: "row" }, h("span", { class: "chip acc" }, `키워드: ${k}`), h("button", { class: "btn ghost sm", type: "button", onclick: () => go("posts", { w, b: board }) }, "해제")));
  const holder = h("div", { class: "card" }, stateBox("불러오는 중…"));
  box.append(holder);
  const mine = renderSeq;
  const posts = await loadPosts(ctx.meta, WINDOW_DAYS[w]);
  if (mine !== renderSeq) return box;
  const from = ctx.trends.windows[w].from;
  const kw = k ? null : q.trim().toLowerCase();
  let rows = posts.filter((p) => p.at >= from && (!board || p.s === board) && (k ? p.k.includes(k) : kw ? p.t.toLowerCase().includes(kw) : p.f === 1));
  rows.sort((a, b) => (a.at < b.at ? 1 : -1));
  const total = rows.length;
  let shown = 100;
  const draw = () => {
    setChildren(holder,
      h("div", { class: "small muted", style: { marginBottom: "6px" } }, `${total.toLocaleString("ko-KR")}건` + (!k && !kw ? " (금융 관련 글만)" : "")),
      total === 0 ? stateBox("조건에 맞는 글이 없습니다.") : rows.slice(0, shown).map((p) => postRow(p, kw || "")),
      total > shown ? h("button", { class: "btn ghost sm", type: "button", onclick: () => { shown += 100; draw(); } }, "더 보기") : null);
  };
  draw();
  return box;
}

// ── 관심 키워드 (이 브라우저에만 저장)
const MAX_WATCH = 5;
const loadWatch = () => store.get("watch", []);
function matchesWatch(item, p) {
  const t = compact(p.t);
  const terms = [item.k, ...(item.s || [])].map(compact).filter(Boolean);
  if (!terms.some((x) => t.includes(x))) return false;
  return !(item.x || []).map(compact).filter(Boolean).some((x) => t.includes(x));
}
async function viewWatch() {
  const box = h("div", { class: "wrap" });
  const list = loadWatch();
  const csv = (id) => $(id).value.split(",").map((s) => s.trim()).filter(Boolean);
  box.append(
    h("div", { class: "card" }, h("h2", null, "관심 키워드 등록 ", h("span", { class: "small muted" }, `(${list.length}/${MAX_WATCH})`)),
      h("form", { class: "field", onsubmit: (e) => {
        e.preventDefault();
        const k = $("wk").value.trim();
        if (!k) return;
        if (list.length >= MAX_WATCH && !list.some((x) => x.k === k)) { alert(`관심 키워드는 ${MAX_WATCH}개까지 등록할 수 있습니다. 기존 키워드를 삭제한 뒤 등록해 주세요.`); return; }
        store.set("watch", [...list.filter((x) => x.k !== k), { k, s: csv("ws"), x: csv("wx") }]);
        render();
      } },
        h("input", { id: "wk", placeholder: "키워드 (예: 스트레스DSR)", "aria-label": "키워드", required: true, maxlength: "40" }),
        h("input", { id: "ws", placeholder: "동의어, 쉼표로 구분", "aria-label": "동의어" }),
        h("input", { id: "wx", placeholder: "제외어, 쉼표로 구분", "aria-label": "제외어" }),
        h("button", { class: "btn", type: "submit" }, "등록")),
      h("p", { class: "small muted", style: { marginTop: "6px" } }, "공백은 무시하고 비교합니다. 등록한 키워드는 이 브라우저에만 저장되며 서버로 보내지 않습니다.")));
  if (list.length === 0) { box.append(stateBox("등록된 관심 키워드가 없습니다.")); return box; }
  const holder = h("div", { class: "wrap" }, stateBox("불러오는 중…"));
  box.append(holder);
  const mine = renderSeq;
  const posts = (await loadPosts(ctx.meta, 5)).sort((a, b) => (a.at < b.at ? 1 : -1));
  if (mine !== renderSeq) return box;
  setChildren(holder, ...list.map((item) => {
    const hits = posts.filter((p) => matchesWatch(item, p));
    return h("div", { class: "card" },
      h("div", { class: "row", style: { marginBottom: "6px" } },
        h("b", null, item.k), h("span", { class: "chip acc" }, `최근 5일 ${hits.length}건`),
        item.s?.length ? h("span", { class: "small muted" }, "동의어 " + item.s.join(", ")) : null,
        item.x?.length ? h("span", { class: "small muted" }, "제외 " + item.x.join(", ")) : null,
        h("button", { class: "btn ghost sm", style: { marginLeft: "auto" }, type: "button", onclick: () => { store.set("watch", list.filter((x) => x.k !== item.k)); render(); } }, "삭제")),
      hits.length === 0 ? h("p", { class: "small muted" }, "최근 5일 안에 맞는 글이 없습니다.") : hits.slice(0, 8).map((p) => postRow(p)),
      hits.length > 8 ? h("button", { class: "btn ghost sm", type: "button", onclick: () => go("posts", { q: item.k }) }, `제목 검색으로 ${hits.length}건 보기`) : null);
  }));
  return box;
}

// ── 게시판 상태
const STATUS = { ok: ["정상", "ok"], empty: ["0건(점검 필요)", "warm"], blocked: ["차단 신호(쉬는 중)", "bad"], disabled: ["수집 중단", "bad"], robots_disallowed: ["robots.txt 금지", "bad"], error: ["오류", "bad"], pending: ["아직 수집 전", ""], no_key: ["API 키 없음", "warm"], off: ["사용 안 함", ""] };
function viewBoards() {
  return h("div", { class: "wrap" },
    h("p", { class: "muted" }, "각 게시판의 robots.txt를 지키며, 차단 신호가 오면 우회하지 않고 쉽니다. 상태가 정상이 아닌 게시판은 집계에서 빠집니다."),
    h("div", { class: "card tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, "게시판"), h("th", null, "상태"), h("th", { class: "n" }, "최근 수집"), h("th", null, "마지막 성공"), h("th", null, "비고"))),
      h("tbody", null, ctx.meta.sources.map((s) => {
        const [label, cls] = STATUS[s.status] || [s.status, ""];
        const url = safeUrl(s.url);
        return h("tr", null,
          h("td", null, url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, `${s.site} ${s.board}`) : `${s.site} ${s.board}`),
          h("td", null, h("span", { class: "chip " + cls }, label)),
          h("td", { class: "n" }, s.last_count ?? "–"),
          h("td", null, s.last_success ? fmtDateTime(s.last_success) : "–"),
          h("td", { class: "small muted" }, s.detail || ""));
      })))),
    notice());
}

// ── 정보
function viewInfo() {
  const upd = h("div", { class: "small muted" }, "확인 전");
  const check = async () => {
    upd.textContent = "확인 중…";
    try {
      const r = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, { headers: { Accept: "application/vnd.github+json" } });
      if (r.status === 404) { upd.textContent = "아직 공개된 릴리스가 없습니다. 이 페이지는 접속할 때마다 최신 상태입니다."; return; }
      if (!r.ok) throw new Error(String(r.status));
      const j = await r.json();
      const latest = String(j.tag_name || "").replace(/^v/, "");
      setChildren(upd, latest && latest !== APP_VERSION
        ? ["새 버전 ", h("b", null, latest), " 이(가) 있습니다. ", h("a", { href: safeUrl(j.html_url) || "#", target: "_blank", rel: "noopener noreferrer", style: { textDecoration: "underline" } }, "릴리스 보기")]
        : "최신 버전입니다.");
    } catch { upd.textContent = "업데이트를 확인하지 못했습니다. 인터넷 연결을 확인해 주세요."; }
  };
  return h("div", { class: "wrap" },
    h("div", { class: "card" }, h("dl", null,
      h("dt", null, "이름"), h("dd", null, APP_NAME),
      h("dt", null, "버전"), h("dd", null, APP_VERSION),
      h("dt", null, "만든이"), h("dd", null, "이현덕 with Claude"),
      h("dt", null, "이메일"), h("dd", null, "hdlee73@gmail.com"),
      h("dt", null, "홈페이지"), h("dd", null, h("a", { href: "https://hdlee73.github.io/Home/", target: "_blank", rel: "noopener noreferrer", style: { textDecoration: "underline" } }, "https://hdlee73.github.io/Home/")),
      h("dt", null, "마지막 갱신"), h("dd", null, ctx.meta ? fmtDateTime(ctx.meta.generated_at) : "–"))),
    h("div", { class: "card" }, h("h2", null, "업데이트"), upd, h("div", { style: { marginTop: "8px" } }, h("button", { class: "btn ghost sm", type: "button", onclick: check }, "업데이트 확인"))),
    h("div", { class: "card" }, h("h2", null, "사용 방법"),
      h("ol", { style: { margin: 0, paddingLeft: "20px", display: "flex", flexDirection: "column", gap: "4px" } },
        h("li", null, "‘금융 키워드 트렌드’에서 오늘·최근 3일·최근 5일을 고르면 많이 언급된 금융·금융회사 키워드가 순위로 나옵니다."),
        h("li", null, "키워드를 누르면 그 키워드가 들어간 게시물 목록이 나오고, 제목을 누르면 원문 게시판으로 이동합니다."),
        h("li", null, "‘관심 키워드’에 단어(동의어·제외어 포함)를 등록하면 최근 5일 글 중 맞는 글을 모아 보여줍니다."),
        h("li", null, "‘급상승’은 최근 24시간 언급이 평소보다 크게 늘어난 키워드입니다. 시스템이 며칠 쌓이기 전에는 비어 있을 수 있습니다."),
        h("li", null, "‘게시판 상태’에서 어느 게시판이 정상 수집 중인지 확인합니다."))),
    h("div", { class: "card" }, h("h2", null, "수집 원칙과 안내"),
      h("p", null, ctx.meta?.notice || ""),
      h("p", { class: "small muted", style: { marginTop: "6px" } }, "네이버 블로그·카페글은 네이버 검색 API(공식)로 찾은 결과의 제목과 링크이며, 검색어별 최신 글만 가져오므로 글 수는 실제보다 적게 잡힐 수 있습니다. 그 밖의 게시판은 robots.txt를 지키고, 같은 사이트에는 6초 이상 간격으로 요청하며, 차단 신호가 오면 우회하지 않고 쉽니다. 게시판 운영자가 원하면 해당 게시판을 즉시 제외하고 데이터를 삭제합니다. 키워드 집계는 참고용이며 투자 권유가 아닙니다.")));
}

// ── 렌더
let renderSeq = 0;
async function render() {
  const seq = ++renderSeq;
  const { id, params } = route();
  document.title = `${MENU.find((m) => m[0] === id)[1]} · ${APP_NAME}`;
  $("title").textContent = MENU.find((m) => m[0] === id)[1];
  renderMenu(id);
  if (!ctx.meta || !ctx.trends) {
    try {
      ctx.meta = await loadMeta();
      ctx.trends = await loadTrends();
      ctx.error = null;
    } catch (e) {
      ctx.error = e;
    }
    if (seq !== renderSeq) return;
    renderMenu(id);
  }
  $("sub").textContent = ctx.meta ? `${fmtDateTime(ctx.meta.generated_at)} 갱신 · 한국시간` : "";
  if (ctx.error || !ctx.meta) {
    if (id === "info") { ctx.meta = ctx.meta || { notice: "", sources: [] }; content.replaceChildren(viewInfo()); return; }
    content.replaceChildren(stateBox("아직 수집된 데이터가 없습니다. 첫 수집이 끝나면 표시됩니다(보통 30분 이내).", h("div", { style: { marginTop: "10px" } }, h("button", { class: "btn ghost sm", type: "button", onclick: refresh }, "다시 불러오기"))));
    return;
  }
  const view = { home: viewHome, heat: viewHeat, trend: viewTrend, spikes: viewSpikes, posts: viewPosts, watch: viewWatch, boards: viewBoards, info: viewInfo }[id];
  try {
    const node = await view(params);
    if (seq !== renderSeq) return;
    content.replaceChildren(node);
    content.scrollTop = 0;
  } catch (e) {
    console.error(e);
    content.replaceChildren(stateBox("화면을 그리지 못했습니다. 새로고침해 주세요."));
  }
}
function refresh() {
  ctx = { meta: null, trends: null, error: null };
  sessionStorage.removeItem("tc.cache");
  render();
}

$("hamb").addEventListener("click", () => document.body.classList.toggle("open"));
$("scrim").addEventListener("click", () => document.body.classList.remove("open"));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.body.classList.remove("open"); });
$("refresh").addEventListener("click", refresh);
window.addEventListener("hashchange", render);
render();
