// 커뮤니티 금융 트렌드: 정적 JSON(data/*.json)만 읽는 단독 웹 화면.
// 모든 글자는 textContent 로만 넣고, 링크는 http(s)만 허용한다(수집 데이터는 외부 입력이므로).
import { dayFiles, loadAlerts, loadFunding, loadMeta, loadPosts, loadTrends } from "./data.js";
import { BOARD_COLORS, fmtDateTime, h, safeUrl, sparkline, store, compact, setChildren, appendKids } from "./ui.js";

export const APP_NAME = "커뮤니티 금융 트렌드";
export const APP_VERSION = "0.1.0";
const REPO = "hdlee73/Test_web";

const MENU = [
  ["monitor", "게시판 모니터링"],
  ["news", "뉴스"],
  ["inquiry", "조회공시/풍문"],
  ["funding", "자금조달"],
  ["board", "게시판"],
  ["trend", "키워드 순위"],
  ["heat", "위험 신호 히트맵"],
  ["spikes", "급상승"],
  ["boards", "수집 현황"],
  ["info", "정보"],
];
// 메뉴에는 없지만 다른 화면의 링크가 쓰는 주소(#/posts?k=금리 처럼): 전체 카테고리 검색
const HIDDEN_ROUTES = ["posts"];
const CATS = [["news", "뉴스"], ["disclosure", "공시"], ["board", "게시판"]];
const STATUS_CATS = [...CATS, ["blog", "블로그"]];
const catName = (c) => (STATUS_CATS.find((x) => x[0] === c) || [c, c])[1];
const WINDOWS = [["today", "오늘"], ["3d", "최근 3일"], ["5d", "최근 5일"]];
const WINDOW_DAYS = { today: 1, "3d": 3, "5d": 5 };

const $ = (id) => document.getElementById(id);
const content = $("content");
let ctx = { meta: null, trends: null, alerts: null, error: null };

// ── 주소(#/화면?키=값)
function route() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  const id = MENU.some((m) => m[0] === path) || HIDDEN_ROUTES.includes(path) ? path : "monitor";
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
    h("button", { class: "mi on", type: "button", "aria-current": "page", onclick: () => { document.body.classList.remove("open"); go("monitor"); } }, APP_NAME),
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
    p.d ? h("span", { class: "chip warm" }, p.d) : null,
    p.a ? h("span", { class: "chip", title: "제목 패턴으로 본 광고·홍보 의심(순위·위험 집계에서 제외)" }, "광고 의심") : null,
    url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, title) : h("span", null, title),
    p.r?.length ? h("span", { class: "chip bad", title: "위험 신호어" }, "⚠ " + p.r.slice(0, 2).join(" · ")) : null,
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
  const sc = CATS.some((x) => x[0] === params.src) ? params.src : "";
  const win = (sc ? ctx.trends.cats?.[sc] : null)?.[w] ?? ctx.trends.windows[w];
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
      segmented(w, (id) => go("trend", { w: id, c: cat, src: sc })),
      h("div", { class: "seg", role: "group", "aria-label": "출처" }, [["", "전체"], ...CATS].map(([id, label]) =>
        h("button", { type: "button", "aria-pressed": String(id === sc), onclick: () => go("trend", { w, c: cat, src: id }) }, label))),
      h("span", { class: "small muted" }, `한국시간 기준 · ${fmtDateTime(win.from)} 이후 · 글 하나에 여러 번 나와도 1건으로 셉니다`)),
    h("div", { class: "cats", role: "group", "aria-label": "분류" },
      [["", "전체"], ...cats.map((c) => [c, c])].map(([id, label]) =>
        h("button", { type: "button", "aria-pressed": String(id === cat), onclick: () => go("trend", { w, c: id, src: sc }) }, label))),
    rows.length === 0
      ? stateBox("이 기간에는 집계된 키워드가 없습니다.")
      : h("div", { class: "card" },
          h("div", { class: "tablewrap" }, h("table", null,
            h("thead", null, h("tr", null, h("th", null, "#"), h("th", null, "키워드"), h("th", { class: "n" }, "글 수"), h("th", null, "게시판 비중"))),
            h("tbody", null, rows.map((k, i) => {
              const total = Object.values(k.sources).reduce((a, b) => a + b, 0) || 1;
              const open = () => go(sc || "posts", { k: k.keyword, w });
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

// ── 위험 신호 히트맵(위험 신호어 × 게시판): 칸을 누르면 그 글 목록
async function viewHeat(params) {
  const w = WINDOWS.some((x) => x[0] === params.w) ? params.w : "3d";
  const holder = h("div", { class: "card tablewrap" }, stateBox("불러오는 중…"));
  const box = h("div", { class: "wrap" },
    h("div", { class: "row" }, segmented(w, (id) => go("heat", { w: id })), h("span", { class: "small muted" }, "숫자 = 그 게시판에서 신호어가 들어간 글 수, 색 = 그 게시판 글 천 건당 비율 · 칸을 누르면 글 목록")),
    holder);
  const mine = renderSeq;
  const from = ctx.trends.windows[w].from;
  const posts = (await loadPosts(ctx.meta, WINDOW_DAYS[w])).filter((p) => p.c === "board" && !p.a && p.at >= from);
  if (mine !== renderSeq) return box;
  const total = {};
  const cnt = {};
  for (const p of posts) {
    total[p.s] = (total[p.s] || 0) + 1;
    for (const t of new Set(p.r || [])) { (cnt[t] ||= {})[p.s] = (cnt[t][p.s] || 0) + 1; }
  }
  const sum = (o) => Object.values(o).reduce((a, b) => a + b, 0);
  const terms = Object.keys(cnt).sort((a, b) => sum(cnt[b]) - sum(cnt[a]) || a.localeCompare(b, "ko")).slice(0, 16);
  const boards = Object.keys(total).sort((a, b) => total[b] - total[a]).slice(0, 12);
  if (terms.length === 0) { setChildren(holder, stateBox("이 기간에 게시판에서 위험 신호어가 들어간 글이 없습니다.")); return box; }
  const per = (t, b) => ((cnt[t][b] || 0) / total[b]) * 1000;
  const peak = Math.max(1, ...terms.flatMap((t) => boards.map((b) => per(t, b))));
  setChildren(holder, h("div", { class: "heat", style: { gridTemplateColumns: `112px repeat(${boards.length}, minmax(48px, 1fr))` } },
    h("div"), boards.map((b) => h("div", { class: "h" }, sourceLabel(b))),
    terms.map((t) => [
      h("div", { class: "hk", style: { cursor: "pointer" }, title: "이 신호어가 든 글 전체 보기", onclick: () => go("board", { r: t, w }) }, t),
      boards.map((b) => {
        const n = cnt[t][b] || 0, v = per(t, b), lv = n === 0 ? 0 : Math.min(4, 1 + Math.floor((v / peak) * 3.999));
        return h("div", { class: "c", style: { background: `var(--h${lv})`, color: lv >= 3 ? "#fff" : "inherit", fontWeight: lv >= 3 ? "600" : "400", cursor: n ? "pointer" : "default" },
          title: `${sourceName(b)} · ${t}: ${n}건 / 글 ${total[b]}건`, onclick: () => n && go("board", { r: t, b, w }) }, n || "");
      })]))),
  appendKids(box, h("div", { class: "legend" }, h("span", null, "적음"), [0, 1, 2, 3, 4].map((l) => h("span", null, h("i", { style: { background: `var(--h${l})` } }))), h("span", null, "많음")), notice());
  return box;
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

// ── 뉴스 / 공시 / 게시판 목록(키워드·위험 신호어·제목 검색)
// rid: 이 화면의 주소 이름, fixedCat: 고정된 카테고리("" 이면 전체 + 카테고리 선택)
async function viewPosts(params, rid = "posts", fixedCat = "") {
  const w = WINDOWS.some((x) => x[0] === params.w) ? params.w : "5d";
  const k = params.k || "";
  const q = params.q || "";
  const board = params.b || "";
  const risk = params.r || "";
  const dtype = params.t || "";
  const showAd = params.ad === "1";
  const cat = fixedCat || (CATS.some((x) => x[0] === params.cat) ? params.cat : "");
  const nav = (o) => go(rid, { w, k, q, b: board, r: risk, t: dtype, ad: showAd ? "1" : "", ...(fixedCat ? {} : { cat }), ...o });
  const box = h("div", { class: "wrap" });
  const form = h("form", { class: "field", onsubmit: (e) => { e.preventDefault(); nav({ k: "", r: "", q: $("q").value.trim() }); } },
    h("input", { id: "q", type: "search", placeholder: "제목에서 검색 (예: 금감원)", value: q, "aria-label": "제목 검색" }),
    h("button", { class: "btn", type: "submit" }, "검색"));
  const srcs = ctx.meta.sources.filter((s) => s.enabled && (!cat || s.category === cat));
  const boardSel = h("select", { "aria-label": "출처", class: "ib", style: { width: "auto", padding: "0 8px" }, onchange: (e) => nav({ b: e.target.value }) },
    h("option", { value: "" }, "모든 출처"),
    ...srcs.map((s) => h("option", { value: s.id, selected: s.id === board }, `${s.site} ${s.board}`)));
  const catSeg = fixedCat ? null : h("div", { class: "seg", role: "group", "aria-label": "카테고리" }, [["", "전체"], ...CATS].map(([id, label]) =>
    h("button", { type: "button", "aria-pressed": String(id === cat), onclick: () => nav({ cat: id, b: "" }) }, label)));
  const dtypeBox = h("span");
  appendKids(box, h("div", { class: "row" }, segmented(w, (id) => nav({ w: id })), catSeg, boardSel, dtypeBox), form);
  const chips = [k && ["키워드", k, { k: "" }], risk && ["위험 신호어", risk, { r: "" }], dtype && ["공시 유형", dtype, { t: "" }]].filter(Boolean);
  if (chips.length) appendKids(box, h("div", { class: "row" }, chips.map(([lab, val, clr]) =>
    h("span", { class: "row" }, h("span", { class: "chip acc" }, `${lab}: ${val}`), h("button", { class: "btn ghost sm", type: "button", onclick: () => nav(clr) }, "해제")))));
  const holder = h("div", { class: "card" }, stateBox("불러오는 중…"));
  appendKids(box, holder);
  const mine = renderSeq;
  const posts = await loadPosts(ctx.meta, WINDOW_DAYS[w]);
  if (mine !== renderSeq) return box;
  const from = ctx.trends.windows[w].from;
  const kw = k || risk || dtype ? null : q.trim().toLowerCase();
  const inCat = posts.filter((p) => p.at >= from && (!cat || p.c === cat) && (!board || p.s === board));
  if (cat === "disclosure" || (!cat && inCat.some((p) => p.d))) {
    const types = [...new Set(inCat.map((p) => p.d).filter(Boolean))].sort();
    if (types.length) setChildren(dtypeBox, h("select", { "aria-label": "공시 유형", class: "ib", style: { width: "auto", padding: "0 8px" }, onchange: (e) => nav({ t: e.target.value }) },
      h("option", { value: "" }, "모든 공시 유형"), ...types.map((t) => h("option", { value: t, selected: t === dtype }, t))));
  }
  const adCount = inCat.filter((p) => p.a).length;
  const rows = inCat.filter((p) => (showAd || !p.a) && (k ? p.k.includes(k) : risk ? p.r?.includes(risk) : dtype ? p.d === dtype : kw ? p.t.toLowerCase().includes(kw) : (cat === "board" ? p.f === 1 : true)));
  rows.sort((a, b) => (a.at < b.at ? 1 : -1));
  const total = rows.length;
  let shown = 100;
  const draw = () => {
    setChildren(holder,
      h("div", { class: "row", style: { marginBottom: "6px" } },
        h("span", { class: "small muted" }, `${total.toLocaleString("ko-KR")}건` + (cat === "board" && !k && !risk && !dtype && !kw ? " (금융 관련 글만)" : "")),
        adCount ? h("button", { class: "btn ghost sm", type: "button", onclick: () => nav({ ad: showAd ? "" : "1" }) }, showAd ? "광고 의심 글 숨기기" : `광고 의심 ${adCount}건 포함해서 보기`) : null),
      total === 0 ? stateBox("조건에 맞는 글이 없습니다.") : rows.slice(0, shown).map((p) => postRow(p, kw || "")),
      total > shown ? h("button", { class: "btn ghost sm", type: "button", onclick: () => { shown += 100; draw(); } }, "더 보기") : null);
  };
  draw();
  return box;
}

// ── 게시판 모니터링: 내가 등록한 키워드 + 기본 위험 신호어(커뮤니티 게시판 글만)
const MAX_WATCH = 5;
const loadWatch = () => store.get("watch", []);
function matchesWatch(item, p) {
  if (p.c !== "board" || p.a) return false; // 게시판 글만, 광고 의심 글은 뺀다
  const t = compact(p.t);
  const terms = [item.k, ...(item.s || [])].map(compact).filter(Boolean);
  if (!terms.some((x) => t.includes(x))) return false;
  return !(item.x || []).map(compact).filter(Boolean).some((x) => t.includes(x));
}
async function viewMonitor(params) {
  const w = WINDOWS.some((x) => x[0] === params.w) ? params.w : "today";
  const list = loadWatch();
  const csv = (id) => $(id).value.split(",").map((s) => s.trim()).filter(Boolean);
  const box = h("div", { class: "wrap" });
  appendKids(box, 
    h("div", { class: "row" }, segmented(w, (id) => go("monitor", { w: id })),
      h("span", { class: "small muted" }, "커뮤니티 게시판 글만 봅니다(뉴스·공시·블로그 제외, 광고 의심 글 제외).")),
    h("div", { class: "card" }, h("h2", null, "내 모니터링 키워드 ", h("span", { class: "small muted" }, `(${list.length}/${MAX_WATCH})`)),
      h("form", { class: "field", onsubmit: (e) => {
        e.preventDefault();
        const k = $("wk").value.trim();
        if (!k) return;
        if (list.length >= MAX_WATCH && !list.some((x) => x.k === k)) { alert(`모니터링 키워드는 ${MAX_WATCH}개까지 등록할 수 있습니다. 기존 키워드를 삭제한 뒤 등록해 주세요.`); return; }
        store.set("watch", [...list.filter((x) => x.k !== k), { k, s: csv("ws"), x: csv("wx") }]);
        render();
      } },
        h("input", { id: "wk", placeholder: "키워드 (예: 스트레스DSR)", "aria-label": "키워드", required: true, maxlength: "40" }),
        h("input", { id: "ws", placeholder: "동의어, 쉼표로 구분", "aria-label": "동의어" }),
        h("input", { id: "wx", placeholder: "제외어, 쉼표로 구분", "aria-label": "제외어" }),
        h("button", { class: "btn", type: "submit" }, "등록")),
      h("p", { class: "small muted", style: { marginTop: "6px" } }, "공백은 무시하고 비교합니다. 등록한 키워드는 이 브라우저에만 저장되며 서버로 보내지 않습니다.")));
  const mineBox = h("div", { style: { display: "flex", flexDirection: "column", gap: "12px" } });
  appendKids(box, mineBox);
  const al = ctx.alerts;
  const cats = Object.entries(al?.windows?.[w] || {});
  const lookup = (uid) => al?.posts?.[uid];
  appendKids(box, 
    h("div", { class: "card" }, h("h2", null, "평소보다 늘어난 위험 신호어(최근 24시간)"),
      !al || al.spikes.length === 0 ? h("p", { class: "small muted" }, "지금은 급증한 신호어가 없습니다. 데이터가 며칠 쌓이면 표시됩니다.")
        : h("div", { class: "row" }, al.spikes.slice(0, 12).map((sp) =>
            h("button", { class: "chip " + (sp.new ? "warm" : "bad"), type: "button", style: { border: 0, cursor: "pointer" }, title: sp.category,
              onclick: () => go("board", { r: sp.term, w: "today" }) }, `${sp.term} ${sp.new ? "NEW" : "×" + sp.ratio} (${sp.recent_24h}건)`)))),
    cats.length === 0 ? stateBox("이 기간에 게시판에서 위험 신호어가 들어간 글이 없습니다.")
      : cats.map(([name, c]) => h("div", { class: "card" },
          h("div", { class: "row" }, h("h2", { style: { margin: 0 } }, name), h("span", { class: "chip bad" }, `${c.posts}건`)),
          h("div", { class: "row", style: { margin: "8px 0" } }, c.terms.map((t) =>
            h("button", { class: "chip", type: "button", style: { border: 0, cursor: "pointer" }, onclick: () => go("board", { r: t.term, w }) }, `${t.term} ${t.posts}`))),
          c.terms.slice(0, 1).flatMap((t) => t.top.slice(0, 3).map(lookup).filter(Boolean)).map((p) => postRow(p)))),
    notice());
  if (list.length === 0) { setChildren(mineBox, stateBox("등록한 모니터링 키워드가 없습니다. 위 칸에 키워드를 등록하면 게시판 글에서 찾아 보여줍니다.")); return box; }
  const mine = renderSeq;
  setChildren(mineBox, stateBox("불러오는 중…"));
  const from = ctx.trends.windows[w].from;
  const posts = (await loadPosts(ctx.meta, WINDOW_DAYS[w])).filter((p) => p.at >= from).sort((a, b) => (a.at < b.at ? 1 : -1));
  if (mine !== renderSeq) return box;
  const label = WINDOWS.find((x) => x[0] === w)[1];
  setChildren(mineBox, list.map((item) => {
    const hits = posts.filter((p) => matchesWatch(item, p));
    return h("div", { class: "card" },
      h("div", { class: "row", style: { marginBottom: "6px" } },
        h("b", null, item.k), h("span", { class: "chip acc" }, `${label} ${hits.length}건`),
        item.s?.length ? h("span", { class: "small muted" }, "동의어 " + item.s.join(", ")) : null,
        item.x?.length ? h("span", { class: "small muted" }, "제외 " + item.x.join(", ")) : null,
        h("button", { class: "btn ghost sm", style: { marginLeft: "auto" }, type: "button", onclick: () => { store.set("watch", list.filter((x) => x.k !== item.k)); render(); } }, "삭제")),
      hits.length === 0 ? h("p", { class: "small muted" }, `${label} 안에 맞는 글이 없습니다.`) : hits.slice(0, 8).map((p) => postRow(p)),
      hits.length > 8 ? h("button", { class: "btn ghost sm", type: "button", onclick: () => go("board", { q: item.k, w }) }, `제목 검색으로 ${hits.length}건 보기`) : null);
  }));
  return box;
}

// ── 뉴스: 최근 12시간 뉴스에서 가장 많이 나온 키워드 10개
async function viewNews(params) {
  const k = params.k || "";
  const q = (params.q || "").trim().toLowerCase();
  const nowMs = Date.parse(ctx.meta.generated_at) || Date.now();
  const sinceMs = nowMs - 12 * 3600 * 1000;
  const holder = h("div", { class: "card" }, stateBox("불러오는 중…"));
  const box = h("div", { class: "wrap" });
  const mine = renderSeq;
  const posts = (await loadPosts(ctx.meta, 2)).filter((p) => p.c === "news" && !p.a && Date.parse(p.at) >= sinceMs);
  if (mine !== renderSeq) return box;
  const count = new Map();
  for (const p of posts) for (const name of new Set(p.k || [])) count.set(name, (count.get(name) || 0) + 1);
  const top = [...count.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ko")).slice(0, 10);
  const max = top[0]?.[1] || 1;
  appendKids(box, 
    h("div", { class: "card" }, h("h2", null, "최근 12시간 뉴스에서 가장 많이 나온 키워드 TOP 10"),
      h("p", { class: "small muted" }, `${fmtDateTime(new Date(sinceMs).toISOString())} 이후 네이버 뉴스 ${posts.length.toLocaleString("ko-KR")}건의 제목 기준 · 한 기사에 여러 번 나와도 1건으로 셉니다`),
      top.length === 0 ? h("p", { class: "small muted" }, "최근 12시간 안에 집계된 키워드가 없습니다.") : top.map(([name, n], i) =>
        h("div", { class: "hrow", tabindex: "0", role: "link", "aria-label": `${name} 기사 보기`, onclick: () => go("news", { k: name }), onkeydown: (e) => { if (e.key === "Enter") go("news", { k: name }); } },
          h("span", { class: "rk" }, i + 1), h("span", { class: "nm" }, name),
          h("span", { class: "bar" }, h("i", { style: { width: (n / max) * 100 + "%" } })), h("span", { class: "num" }, n)))),
    h("form", { class: "field", onsubmit: (e) => { e.preventDefault(); go("news", { k: "", q: $("q").value.trim() }); } },
      h("input", { id: "q", type: "search", placeholder: "기사 제목에서 검색", value: params.q || "", "aria-label": "제목 검색" }),
      h("button", { class: "btn", type: "submit" }, "검색")),
    k ? h("div", { class: "row" }, h("span", { class: "chip acc" }, `키워드: ${k}`), h("button", { class: "btn ghost sm", type: "button", onclick: () => go("news") }, "해제")) : null,
    holder);
  const rows = posts.filter((p) => (k ? p.k.includes(k) : q ? p.t.toLowerCase().includes(q) : true)).sort((a, b) => (a.at < b.at ? 1 : -1));
  let shown = 60;
  const draw = () => setChildren(holder,
    h("div", { class: "small muted", style: { marginBottom: "6px" } }, `${rows.length.toLocaleString("ko-KR")}건`),
    rows.length === 0 ? stateBox("조건에 맞는 기사가 없습니다.") : rows.slice(0, shown).map((p) => postRow(p, q)),
    rows.length > shown ? h("button", { class: "btn ghost sm", type: "button", onclick: () => { shown += 60; draw(); } }, "더 보기") : null);
  draw();
  return box;
}

// ── 조회공시/풍문: 최근 5일(DART·KIND)
const INQUIRY = /조회\s*공시|풍문|보도에\s*대한/;
async function viewInquiry(params) {
  const t = ["req", "ans"].includes(params.t) ? params.t : "";
  const q = (params.q || "").trim().toLowerCase();
  const holder = h("div", { class: "card" }, stateBox("불러오는 중…"));
  const box = h("div", { class: "wrap" });
  const kindOf = (p) => (/요구/.test(p.t) ? "req" : /답변|해명|미확정|부인/.test(p.t) ? "ans" : "");
  appendKids(box, 
    h("p", { class: "muted" }, "거래소가 풍문·보도에 대해 해명을 요구하는 ‘조회공시요구’와 회사의 ‘답변·해명’ 공시만 최근 5일치를 모았습니다. DART와 KIND에 같이 올라온 공시는 한 번만 셉니다."),
    h("div", { class: "row" }, h("div", { class: "seg", role: "group", "aria-label": "구분" }, [["", "전체"], ["req", "조회공시 요구"], ["ans", "답변·해명"]].map(([id, label]) =>
      h("button", { type: "button", "aria-pressed": String(id === t), onclick: () => go("inquiry", { t: id, q: params.q || "" }) }, label)))),
    h("form", { class: "field", onsubmit: (e) => { e.preventDefault(); go("inquiry", { t, q: $("q").value.trim() }); } },
      h("input", { id: "q", type: "search", placeholder: "회사명·제목 검색", value: params.q || "", "aria-label": "제목 검색" }),
      h("button", { class: "btn", type: "submit" }, "검색")),
    holder);
  const mine = renderSeq;
  const from = ctx.trends.windows["5d"].from;
  const posts = (await loadPosts(ctx.meta, 5)).filter((p) => p.c === "disclosure" && p.at >= from && INQUIRY.test(p.t));
  if (mine !== renderSeq) return box;
  const rows = posts.filter((p) => (!t || kindOf(p) === t) && (!q || p.t.toLowerCase().includes(q))).sort((a, b) => (a.at < b.at ? 1 : -1));
  const req = posts.filter((p) => kindOf(p) === "req").length;
  setChildren(holder,
    h("div", { class: "small muted", style: { marginBottom: "6px" } }, `${rows.length.toLocaleString("ko-KR")}건 (최근 5일 전체 ${posts.length}건, 조회공시 요구 ${req}건)`),
    rows.length === 0 ? stateBox("조건에 맞는 공시가 없습니다. (DART 키가 없으면 KIND 공시만 보입니다.)") : rows.slice(0, 300).map((p) => postRow(p, q)));
  return box;
}

// ── 자금조달: 최근 5일 증권신고서 제출 현황(펀드 제외)
async function viewFunding() {
  const box = h("div", { class: "wrap" });
  const mine = renderSeq;
  const data = await loadFunding();
  if (mine !== renderSeq) return box;
  const dsrc = ctx.meta.sources.find((s) => s.id === "dart_funding");
  if (dsrc && dsrc.status === "no_key") return h("div", { class: "wrap" }, stateBox("DART API 키가 없어 증권신고서 현황을 받지 못했습니다. 저장소 Secrets 에 DART_API_KEY 를 추가해 주세요."));
  const cutoff = (() => { const d = new Date(Date.parse(ctx.meta.generated_at) + 9 * 3600e3 - 4 * 86400e3); return d.toISOString().slice(0, 10).replaceAll("-", ""); })();
  const items = (data?.items || []).filter((x) => x.rcept_dt >= cutoff);
  if (!data || items.length === 0) return h("div", { class: "wrap" }, stateBox("최근 5일 안에 제출된 증권신고서가 없거나 아직 집계 전입니다."));
  const total = items.reduce((a, x) => a + (x.amount_eok || 0), 0);
  const byKind = {};
  for (const x of items) { const b = (byKind[x.kind] ||= { n: 0, eok: 0 }); b.n += 1; b.eok += x.amount_eok || 0; }
  const eok = (v) => (v == null ? "–" : v.toLocaleString("ko-KR", { maximumFractionDigits: 1 }));
  const d8 = (s) => (s && s.length === 8 ? `${s.slice(4, 6)}.${s.slice(6, 8)}` : s || "–");
  appendKids(box, 
    h("p", { class: "muted" }, "DART 증권신고서(정정 포함)를 증권 종류별로 정리했습니다. 펀드(집합투자증권)는 제외했고, 모집(매출)총액은 억원 단위입니다. 정정 신고서는 제출 때마다 한 줄로 나옵니다."),
    h("div", { class: "kpis" }, kpi(String(items.length), "최근 5일 제출 건수"), kpi(eok(total), "모집(매출)총액 합계(억원)"),
      ...Object.entries(byKind).slice(0, 2).map(([name, b]) => kpi(`${b.n}건 · ${eok(b.eok)}억`, name))),
    h("div", { class: "card tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, "접수일"), h("th", null, "회사"), h("th", null, "신고서"), h("th", null, "증권 종류"),
        h("th", { class: "n" }, "모집(매출)규모(억원)"), h("th", null, "청약일"), h("th", null, "납입일"), h("th", null, "공시"))),
      h("tbody", null, items.map((x) => {
        const url = safeUrl(x.url);
        return h("tr", null,
          h("td", null, d8(x.rcept_dt)),
          h("td", null, h("b", null, x.corp_name), x.stock_code ? h("span", { class: "small muted" }, ` ${x.stock_code}`) : null),
          h("td", null, h("span", { class: "chip" }, x.kind), x.corrected ? h("span", { class: "chip warm" }, "정정") : null, x.from_original ? h("span", { class: "chip", title: "이 정정·확정 신고서가 아니라 앞서 제출한 신고서의 규모·일정입니다. 원문에서 확인하세요." }, "앞선 신고서 기준") : null),
          h("td", null, x.security || "–"),
          h("td", { class: "n" }, eok(x.amount_eok)),
          h("td", null, x.sub_date || "–"),
          h("td", null, x.pay_date || "–"),
          h("td", null, url ? h("a", { class: "btn ghost sm", href: url, target: "_blank", rel: "noopener noreferrer" }, "공시 보기") : "–"));
      })))),
    notice());
  return box;
}

// ── 게시판 상태
const STATUS = { ok: ["정상", "ok"], empty: ["0건(점검 필요)", "warm"], blocked: ["차단 신호(쉬는 중)", "bad"], disabled: ["수집 중단", "bad"], robots_disallowed: ["robots.txt 금지", "bad"], error: ["오류", "bad"], pending: ["아직 수집 전", ""], no_key: ["API 키 없음", "warm"], off: ["사용 안 함", ""] };
function viewBoards() {
  const row = (s) => {
    const [label, cls] = STATUS[s.status] || [s.status, ""];
    const url = safeUrl(s.url);
    return h("tr", null,
      h("td", null, url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, `${s.site} ${s.board}`) : `${s.site} ${s.board}`),
      h("td", null, h("span", { class: "chip " + cls }, label)),
      h("td", { class: "n" }, s.last_count ?? "–"),
      h("td", null, s.last_success ? fmtDateTime(s.last_success) : "–"),
      h("td", { class: "small muted" }, s.off_reason || s.detail || ""));
  };
  const head = h("thead", null, h("tr", null, h("th", null, "소스"), h("th", null, "상태"), h("th", { class: "n" }, "최근 수집"), h("th", null, "마지막 성공"), h("th", null, "비고(제외 사유 포함)")));
  return h("div", { class: "wrap" },
    h("p", { class: "muted" }, "공시는 DART 오픈API와 거래소 KIND, 뉴스·블로그는 네이버 검색 API(공식)로 받고, 게시판은 robots.txt를 지킵니다. 차단 신호가 오면 우회하지 않고 쉬며, 정상이 아닌 소스는 집계에서 빠집니다."),
    STATUS_CATS.map(([cat, name]) => {
      const list = ctx.meta.sources.filter((s) => (s.category || "board") === cat);
      if (cat === "blog" && !list.length) return null;
      return h("div", { class: "card tablewrap" }, h("h2", null, name), h("table", null, head, h("tbody", null, list.map(row))));
    }),
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
        h("li", null, "‘게시판 모니터링’은 커뮤니티 게시판 글에서 위험 신호어(유사수신·리딩방·불완전판매·환매 중단·횡령·정보 유출 등)와, 내가 등록한 키워드(최대 5개, 동의어·제외어 가능)가 든 글을 찾아 줍니다. 최근 24시간에 평소보다 크게 늘어난 신호어도 알려 줍니다."),
        h("li", null, "‘뉴스’는 최근 12시간 네이버 뉴스 제목에서 가장 많이 나온 키워드 10개를 보여주고, 키워드를 누르면 해당 기사 목록이 나옵니다."),
        h("li", null, "‘조회공시/풍문’은 최근 5일 동안 거래소가 풍문·보도에 대해 요구한 조회공시와 회사의 답변·해명 공시만 모았습니다."),
        h("li", null, "‘자금조달’은 최근 5일 증권신고서(펀드 제외)를 증권 종류, 모집(매출)규모(억원), 청약일, 납입일로 정리하고 ‘공시 보기’로 DART 원문에 연결합니다."),
        h("li", null, "‘게시판’은 커뮤니티 게시판 글을 검색하고, ‘위험 신호 히트맵’은 위험 신호어가 어느 게시판에 많은지 보여주며 칸을 누르면 글 목록이 나옵니다."),
        h("li", null, "‘키워드 순위’는 오늘·최근 3일·최근 5일에 많이 언급된 금융·금융회사 키워드이고, ‘급상승’은 최근 24시간에 크게 늘어난 키워드입니다. 데이터가 며칠 쌓이기 전에는 비어 있을 수 있습니다."),
        h("li", null, "‘수집 현황’에서 소스별 상태와, 수집하지 않는 곳의 제외 사유를 확인합니다."))),    h("div", { class: "card" }, h("h2", null, "수집 원칙과 안내"),
      h("p", null, ctx.meta?.notice || ""),
      h("p", { class: "small muted", style: { marginTop: "6px" } }, "네이버 블로그·카페글은 네이버 검색 API(공식)로 찾은 결과의 제목과 링크이며, 검색어별 최신 글만 가져오므로 글 수는 실제보다 적게 잡힐 수 있습니다. 그 밖의 게시판은 robots.txt를 지키고, 같은 사이트에는 6초 이상 간격으로 요청하며, 차단 신호가 오면 우회하지 않고 쉽니다. 게시판 운영자가 원하면 해당 게시판을 즉시 제외하고 데이터를 삭제합니다. 키워드 집계는 참고용이며 투자 권유가 아닙니다.")));
}

// ── 렌더
let renderSeq = 0;
async function render() {
  const seq = ++renderSeq;
  const { id, params } = route();
  const pageName = (MENU.find((m) => m[0] === id) || [0, "게시물 검색"])[1];
  document.title = `${pageName} · ${APP_NAME}`;
  $("title").textContent = pageName;
  renderMenu(id);
  if (!ctx.meta || !ctx.trends) {
    try {
      ctx.meta = await loadMeta();
      [ctx.trends, ctx.alerts] = await Promise.all([loadTrends(), loadAlerts()]);
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
  const view = { monitor: viewMonitor, news: viewNews, inquiry: viewInquiry, funding: viewFunding, board: (p) => viewPosts(p, "board", "board"), posts: (p) => viewPosts(p, "posts", ""), heat: viewHeat, trend: viewTrend, spikes: viewSpikes, boards: viewBoards, info: viewInfo }[id];
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
  ctx = { meta: null, trends: null, alerts: null, error: null };
  sessionStorage.removeItem("tc.cache");
  render();
}

$("hamb").addEventListener("click", () => document.body.classList.toggle("open"));
$("scrim").addEventListener("click", () => document.body.classList.remove("open"));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.body.classList.remove("open"); });
$("refresh").addEventListener("click", refresh);
window.addEventListener("hashchange", render);
render();
