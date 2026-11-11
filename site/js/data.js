// 정적 JSON 읽기. 접속할 때마다 최신을 받도록 meta.json 은 캐시를 건너뛰고,
// 나머지 파일은 meta.generated_at 을 주소에 붙여 갱신 때만 새로 받는다.
const BASE = "data/";

async function getJson(path, { fresh = false, version = "" } = {}) {
  const url = BASE + path + (version ? `?v=${encodeURIComponent(version)}` : "");
  const r = await fetch(url, { cache: fresh ? "no-store" : "default" });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

let version = "";
export async function loadMeta() {
  const meta = await getJson("meta.json", { fresh: true });
  version = meta.generated_at || "";
  return meta;
}
export const loadTrends = () => getJson("trends.json", { version });

/** meta.post_files(최신 → 과거) 중 앞의 days 개. */
export function dayFiles(meta, days) {
  return [...(meta.post_files || [])].sort().reverse().slice(0, days);
}

const postCache = new Map();
/** 최근 days 일 게시물 전체(일자 파일은 한 번만 받는다). 일부 파일이 없어도 나머지로 계속한다. */
export async function loadPosts(meta, days) {
  const files = dayFiles(meta, days);
  const parts = await Promise.all(files.map(async (f) => {
    const key = f + "@" + version;
    if (!postCache.has(key)) {
      postCache.set(key, getJson(f, { version }).then((j) => j.posts || []).catch(() => []));
    }
    return postCache.get(key);
  }));
  return parts.flat();
}
