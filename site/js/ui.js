// 화면 공통 도구: DOM 만들기, 안전한 링크, 시간 표시, 브라우저 저장소.
export const BOARD_COLORS = ["#1f6feb", "#5f97f0", "#a9c8f8", "#f59e0b", "#f8c477", "#47638a", "#8ea3c4", "#c7d1e0", "#2a9d8f", "#9b72cf", "#d1708f", "#7c8b3a", "#b5651d", "#4b8f9e"];

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, v);
    }
  }
  append(el, children);
  return el;
}
function append(el, children) {
  for (const c of children) {
    if (c == null || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

/** http(s) 주소만 통과. 그 밖(javascript: 등)은 null. */
export function safeUrl(u) {
  try {
    const x = new URL(String(u));
    return x.protocol === "https:" || x.protocol === "http:" ? x.href : null;
  } catch {
    return null;
  }
}

const KST = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
export function fmtDateTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  const p = Object.fromEntries(KST.formatToParts(d).map((x) => [x.type, x.value]));
  return `${p.month}.${p.day} ${p.hour === "24" ? "00" : p.hour}:${p.minute}`;
}

export const compact = (s) => String(s || "").normalize("NFKC").replace(/\s+/g, "").toLowerCase();

export const store = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem("tc." + key);
      return v == null ? fallback : JSON.parse(v);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem("tc." + key, JSON.stringify(value));
    } catch {
      /* 저장이 막힌 브라우저: 저장 없이 계속 */
    }
  },
};

/** 값 배열로 작은 꺾은선 SVG 를 만든다(키워드별 추이용). */
export function sparkline(values, { width = 120, height = 28 } = {}) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width);
  svg.setAttribute("height", height);
  svg.setAttribute("class", "spark");
  const max = Math.max(1, ...values);
  const pts = values.map((v, i) => `${(i * (width - 4)) / Math.max(1, values.length - 1) + 2},${height - 3 - (v / max) * (height - 6)}`).join(" ");
  const pl = document.createElementNS(ns, "polyline");
  pl.setAttribute("points", pts);
  pl.setAttribute("fill", "none");
  pl.setAttribute("stroke", "currentColor");
  pl.setAttribute("stroke-width", "2");
  svg.append(pl);
  return svg;
}
