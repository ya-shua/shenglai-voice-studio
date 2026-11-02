/* 声来：以「当前音色」为主角的任务流工作台（原生 JS，无依赖） */
"use strict";

const CAT_PRIORITY = ["女声", "男声", "普通话", "粤语", "台湾腔", "温柔型", "活力型",
  "沉稳型", "播报", "方言", "推荐", "双语", "多语", "英文", "日语", "韩语",
  "新闻", "小说", "对话", "有声书", "通用", "文章"];

function sortCats(cats) {
  return cats.sort((a, b) => {
    const ia = CAT_PRIORITY.indexOf(a), ib = CAT_PRIORITY.indexOf(b);
    return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
  });
}

const GENDER_TAGS = ["女声", "男声"];
const LANG_TAGS = ["普通话", "粤语", "台湾腔", "方言", "双语", "多语", "英文", "日语", "韩语"];

/* 风格标签 = 剔除性别与语言之后的标签（温柔型 / 活力型 / 沉稳型 / 播报…） */
function styleTagsOf(list) {
  return sortCats([...new Set(list.flatMap((v) => v.tags || []))]
    .filter((t) => !GENDER_TAGS.includes(t) && !LANG_TAGS.includes(t)));
}

/* 重建「风格」下拉：只列当前模型下真正出现过的风格标签 */
function fillHallStyle(list) {
  const sel = $("#hall-style");
  if (!sel) return;
  const cur = sel.value;
  const tags = styleTagsOf(list);
  sel.innerHTML = `<option value="">全部风格</option>` +
    tags.map((c) => `<option>${esc(c)}</option>`).join("");
  if (cur && tags.includes(cur)) sel.value = cur;
}

// 真实版本由 server.py 注入（window.__APP_VERSION__），不再手写——手写会与后端版本永远不等，
// 导致「面板已更新」横幅常驻、点刷新也不消失。
const CLIENT_VERSION = String(window.__APP_VERSION__ || "").trim();
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = { current: "", voices: [], status: null };

const AUTO_TEXTS = [
  "大家好，我是小美。今天天气不错，我们出门走走，顺便买一杯冰美式，晚上再一起看一场电影。",
  "生活就是这样，平凡的日子里也藏着小惊喜。记得多喝水，早点休息，明天又是元气满满的一天。",
  "如果问我最喜欢什么季节，那一定是秋天，风很温柔，天很高，走在路上连心情都变得开阔了。",
];

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

let toastTimer = null;
function toast(msg, ok = true) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (ok ? "" : " err");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), ok ? 3200 : 7000);
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function busy(btn, on, textBusy) {
  if (on) {
    btn.dataset.orig = btn.textContent;
    btn.textContent = textBusy || "处理中…";
    btn.disabled = true;
  } else {
    btn.textContent = btn.dataset.orig || btn.textContent;
    btn.disabled = false;
  }
}

/* ---------------- 音色登记表（当前音色的唯一数据源） ---------------- */

async function loadVoices() {
  const [vRes, mRes] = await Promise.all([
    api("/api/voices").catch(() => ({ voices: [] })),
    api("/api/material-voices").catch(() => ({ voices: [] })),
  ]);
  const reg = new Map(vRes.voices.map((v) => [v.name, v]));
  const names = [];
  for (const n of mRes.voices) if (!names.includes(n)) names.push(n);
  for (const v of vRes.voices) if (!names.includes(v.name)) names.push(v.name);
  state.voices = names.map((n) => reg.get(n) || { name: n, provider: "", status: "素材待注册", materials: true });

  const sel = $("#cur-voice");
  const usable = state.voices.filter((v) => v.status !== "failed");
  sel.innerHTML = usable.map((v) => {
    const tag = v.provider ? `（${v.provider}）` : "（素材待注册）";
    return `<option value="${esc(v.name)}">${esc(v.name)} ${esc(tag)}</option>`;
  }).join("") || `<option value="">（还没有音色，点「开始创建」）</option>`;
  if (!state.current || !usable.some((v) => v.name === state.current)) {
    let saved = "";
    try { saved = localStorage.getItem("shenglai.voice") || ""; } catch (err) {}
    state.current = (saved && usable.some((v) => v.name === saved)) ? saved : (usable.length ? usable[0].name : "");
  } else {
    sel.value = state.current;
  }
  if (state.current) {
    sel.value = state.current;
    try { localStorage.setItem("shenglai.voice", state.current); } catch (err) {}
  }
  renderCurrent();
  renderVoices();
}

function currentVoice() {
  return state.voices.find((v) => v.name === state.current) || null;
}

async function renderVoices() {
  const box = $("#voice-list");
  if (!box) return;
  try {
    const { voices } = await api("/api/voices");
    const reg = new Map(voices.map((v) => [v.name, v]));
    const merged = state.voices.map((v) => reg.get(v.name) || v);
    const usable = merged.filter((v) => (v.status || "ready") !== "failed");
    $("#home-list").hidden = usable.length === 0;
    const mc = $("#mine-count");
    if (mc) mc.textContent = usable.length ? `${usable.length} 个` : "（空）";
    if (!usable.length) {
      box.innerHTML = `<p class="hint">还没有音色——用上面的方式创建一个吧。</p>`;
      return;
    }
    box.innerHTML = usable.map((v) => {
      const hue = hueOf(v.name);
      const initial = (v.name || "?").slice(0, 1);
      return `
      <div class="voicecard" data-name="${esc(v.name)}">
        <div class="vhead">
          <span class="avatar" style="background:hsl(${hue},55%,42%)">${esc(initial)}</span>
          <div><b>${esc(v.name)}</b> <span class="dim">${esc(v.status || "ready")}</span></div>
        </div>
        <div class="dim">${esc(v.provider || "待注册")} · ${esc(v.voice_id || "-")}</div>
        <div class="dim">模型: ${esc(v.target_model || "默认")} · 素材 ${(v.materials || []).length} 个</div>
        <div class="actions">
          <button data-try="${esc(v.name)}">去说话</button>
          <button data-del="${esc(v.name)}">删除</button>
        </div>
      </div>`;
    }).join("");
    box.querySelectorAll("[data-try]").forEach((b) =>
      b.addEventListener("click", () => {
        state.current = b.dataset.try;
        try { localStorage.setItem("shenglai.voice", state.current); } catch (err) {}
        loadVoices();
        switchTask("speak");
      })
    );
    box.querySelectorAll("[data-del], [data-delcloud]").forEach((b) =>
      b.addEventListener("click", async () => {
        if (b.dataset.armed !== "1") {
          b.dataset.armed = "1";
          b.dataset.orig = b.textContent;
          b.textContent = b.dataset.orig === "删除" ? "确认删除?" : "确认连云端删?";
          b.style.borderColor = "#ff6b6b";
          setTimeout(() => {
            if (b.isConnected && b.dataset.armed === "1") {
              b.dataset.armed = "";
              b.textContent = b.dataset.orig;
              b.style.borderColor = "";
            }
          }, 3000);
          return;
        }
        const name = b.dataset.del || b.dataset.delcloud;
        const alsoCloud = b.dataset.delcloud !== undefined;
        try {
          const res = await api("/api/voices/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ voice_name: name, also_cloud: alsoCloud }),
          });
          toast(`已删除「${name}」` + (res.cloud || "（仅本地）"));
          if (state.current === name) {
            state.current = "";
            try { localStorage.removeItem("shenglai.voice"); } catch (err) {}
          }
          loadVoices();
          loadSingStatus();
        } catch (e) { toast("删除失败: " + e.message, false); }
      })
    );
  } catch (e) { /* ignore */ }
}

function renderCurrent() {
  const v = currentVoice();
  const has = state.voices.length > 0;
  const set = (id, val) => { const el = $(id); if (el) el.hidden = val; };
  set("#cur-wrap", !has);
  $("#btn-new").textContent = has ? "＋ 新建音色" : "开始创建";
  set("#home-list", !has);
  set("#speak-pointer", !!v);
  set("#speak-main", !v);
  $("#sp-voice-label").textContent = v ? v.name : "（未选择音色）";
  $("#mt-voice-label").textContent = v ? v.name : "（未选择音色）";
  if (v) {
    showMaterials();
    renderCoverVoices();
  }
}

async function loadStatus() {
  try {
    const st = await api("/api/status");
    state.status = st;
    if (st.version && CLIENT_VERSION && st.version !== CLIENT_VERSION) {
      const b = $("#upd-banner");
      b.classList.remove("hidden");
      b.innerHTML = "🔁 面板已更新到 v" + esc(st.version) + "（当前页面是旧版，功能可能不全）——" +
        '<button class="mini primary" onclick="location.reload()" type="button">点击刷新启用新版本</button>';
    }
    const chip = $("#status-chip");
    chip.textContent = st.any_provider ? "已就绪" : "未接入模型";
    chip.className = "chip" + (st.any_provider ? " ok" : " warn");
  } catch (e) {
    $("#status-chip").textContent = "服务异常";
  }
}

const PAGE_TITLES = {
  hall: "音色大厅", speak: "说话", create: "造声音",
  mine: "我的音色", cover: "翻唱", settings: "模型接入", guide: "使用指南",
};

function switchTask(name) {
  $$("#side-nav button, .side-foot button").forEach((b) => b.classList.toggle("active", b.dataset.task === name));
  // class 与 hidden 双保险：面板页初始靠 hidden 属性隐藏，只切 class 会导致页面不切换
  $$(".task").forEach((t) => {
    const on = t.id === "task-" + name;
    t.classList.toggle("active", on);
    t.hidden = !on;
  });
  const title = $("#page-title");
  if (title) title.textContent = PAGE_TITLES[name] || "声来";
  if (name === "hall") loadHall();
  if (name === "speak") loadOutputs();
  if (name === "create") { renderVoices(); loadCloneModels(); }
  if (name === "mine") { renderVoices(); showMaterials(); loadMaterialSourceVoices(); }
  if (name === "cover") loadCover();
  if (name === "settings") renderProviderRows();
}

/* ---------------- MiMo 快速合成台 ---------------- */

let mimoMode = "builtin";


async function loadCloneModels() {
  try {
    const { providers } = await api("/api/providers");
    const usable = providers.filter(
      (p) => p.configured && (p.id === "mimo" || (p.capabilities.includes("enroll") && p.capabilities.includes("tts")))
    );
    const sel = $("#mm-clone-model");
    if (!usable.length) {
      sel.innerHTML = `<option value="mimo">小米 MiMo TTS（未接入）</option>`;
      $("#mm-clone-hint").textContent = "先在「模型接入」里接入一家支持克隆的模型（推荐 MiMo，免费）";
      return;
    }
    sel.innerHTML = usable.map((p) => `<option value="${esc(p.id)}">${esc(p.display_name)}${p.id === "mimo" ? "（直传克隆）" : "（临时注册→合成→清理）"}</option>`).join("");
    $("#mm-clone-hint").textContent = "";
  } catch (e) { /* ignore */ }
}

function readCloneFile() {
  return new Promise((resolve, reject) => {
    const file = ($("#mm-ref").files || [])[0];
    if (!file) return reject(new Error("请选参考音频（mp3/wav，10~30 秒）"));
    if (file.size > 7500000) return reject(new Error("参考音频太大（base64 后需 ≤10MB），请剪到 30 秒内"));
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(new Error("读取文件失败"));
    fr.readAsDataURL(file);
  });
}



/* ---------------- 新建音色（🏠 我的声音页内） ---------------- */

function switchIntent(intent) {
  $$(".wizintent").forEach((b) => b.classList.toggle("active", b.dataset.intent === intent));
  $("#wiz-design").hidden = intent !== "design";
  $("#wiz-clone").hidden = intent !== "clone";
  $("#wiz-pick").hidden = intent !== "pick";
  if (intent === "library") loadHall();
}

function setCurrentAndRefresh(name) {
  const first = state.voices.length === 0;
  state.current = name;
  loadVoices();
  switchTask("speak");
  if (first) toast("🎉 第一个音色就绪！已切换到「说话」，让它开口吧");
}

/* 造声音：百炼要选目标模型，MiMo 免费版不需要 */
function syncDesignProvider() {
  const prov = $("#vd-provider").value;
  const row = $("#vd-model-row");
  const hint = $("#vd-mimo-hint");
  if (row) row.style.display = prov === "bailian" ? "" : "none";
  if (hint) hint.hidden = prov !== "mimo";
}

async function runDesign() {
  const btn = $("#vd-run");
  const provider = $("#vd-provider").value;
  const payload = {
    voice_name: $("#vd-name").value.trim(),
    description: $("#vd-desc").value.trim(),
    preview_text: $("#vd-preview").value.trim() || null,
    provider: provider,
    target_model: provider === "bailian" ? $("#vd-model").value : "",
    save_preview_material: $("#vd-save-mat").checked,
  };
  if (!payload.voice_name || !payload.description) return toast("音色名与声音描述必填", false);
  busy(btn, true, "生成中…（约20~60秒）");
  const box = $("#vd-result");
  box.className = "result"; box.classList.remove("hidden");
  box.textContent = "正在按描述生成音色…";
  try {
    const res = await api("/api/voices/design", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const v = res.voice;
    box.className = "result ok";
    box.textContent = `✅ 音色「${v.name}」已生成并设为当前音色\nvoice_id: ${v.voice_id} · 模型: ${v.target_model}\n收起向导后去 🎤 说话试试`;
    if (v.notice) box.textContent += "\n⚠ " + v.notice;
    if (v.preview_url) {
      const player = $("#vd-player");
      player.src = v.preview_url + "&t=" + Date.now();
      player.classList.remove("hidden");
      player.play().catch(() => {});
    }
    setCurrentAndRefresh(v.name);
  } catch (e) {
    box.className = "result err";
    box.textContent = "生成失败：" + e.message;
  }
  busy(btn, false);
}

async function runClone() {
  const btn = $("#qc-run");
  const file = ($("#mm-ref").files || [])[0];
  if (!file) return toast("请选参考音频（mp3/wav，10~30 秒清晰人声）", false);
  if (file.size > 7500000) return toast("参考音频太大（base64 后需 ≤10MB），请剪到 30 秒内", false);
  const provider = $("#mm-clone-model").value || "mimo";
  const keep = $("#qc-keep").value === "1";
  const text = $("#qc-text").value;
  if (!text.trim()) return toast("请填要让它说的话", false);
  if (keep && !$("#qc-name").value.trim()) return toast("保留音色需要填音色名", false);
  busy(btn, true, "克隆中…（约20~60秒）");
  const box = $("#qc-result");
  box.className = "result"; box.classList.remove("hidden");
  box.textContent = "上传参考音频 → 克隆合成中…";
  try {
    const dataUri = await readCloneFile();
    const data = await api("/api/clone-universal", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, text, ref_data_uri: dataUri, keep }),
    });
    box.className = "result ok";
    box.textContent = `✅ ${data.file}（${(data.size / 1024).toFixed(0)} KB${data.kept ? " · 已保留为新音色" : " · 试听模式"}）`;
    const player = $("#qc-player");
    player.src = data.url + "&t=" + Date.now();
    player.classList.remove("hidden");
    player.play().catch(() => {});
    if (data.kept && data.voice) setCurrentAndRefresh(data.voice);
  } catch (e) {
    box.className = "result err";
    box.textContent = "失败：" + e.message;
  }
  busy(btn, false);
}

async function loadPickCatalog() {
  const provider = $("#pk-provider").value;
  const sel = $("#pk-select");
  $("#pk-model-row").hidden = provider !== "bailian";
  const doLoad = async () => {
    try {
      const res = await api("/api/catalog?provider=" + encodeURIComponent(provider));
      if (!(res.items || []).length) {
        sel.innerHTML = `<option value="">（目录为空）</option>`;
        return toast(provider === "bailian" ? "官方目录为空" : "账号下暂无模型，先在官网训练/克隆");
      }
      sel.innerHTML = res.items.map((it) =>
        `<option value="${esc(it.voice_id)}">${esc(it.name || it.voice_id)}</option>`).join("");
      toast(`拉取到 ${res.items.length} 个音色`);
    } catch (e) { toast("拉取失败: " + e.message, false); }
  };
  if (provider === "bailian") return doLoad();
  ensureProvider(provider, doLoad);
}

async function registerPick() {
  const provider = $("#pk-provider").value;
  const voiceId = $("#pk-custom").value.trim() || $("#pk-select").value;
  const name = $("#pk-name").value.trim();
  if (!name) return toast("请填音色名", false);
  if (!voiceId) return toast("请拉取目录或手动填 ID", false);
  const payload = { voice_name: name, provider, voice_id: voiceId };
  if (provider === "bailian") payload.target_model = $("#pk-model").value;
  try {
    await api("/api/voices/manual", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    toast(`音色「${name}」已登记并设为当前`);
    $("#pk-name").value = ""; $("#pk-custom").value = "";
    setCurrentAndRefresh(name);
  } catch (e) { toast("登记失败: " + e.message, false); }
}

/* ---------------- 🎤 说话 ---------------- */

async function runTTS() {
  const v = currentVoice();
  if (!v) return toast("请先「＋新建音色」或在右上选择音色", false);
  if (v.provider === "kits") return toast("Kits 音色是唱歌用的，说话请选其他音色", false);
  const btn = $("#tts-run");
  const payload = {
    text: $("#tts-text").value,
    voice_name: v.name,
    rate: parseFloat($("#tts-rate").value) || 1.0,
    pitch: parseFloat($("#tts-pitch").value) || 1.0,
    volume: parseInt($("#tts-volume").value, 10) || 50,
    format: $("#tts-format").value,
  };
  busy(btn, true, "合成中…");
  const box = $("#tts-result");
  box.className = "result"; box.classList.remove("hidden");
  box.textContent = "正在合成…";
  try {
    const res = await api("/api/tts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    box.className = "result ok";
    box.textContent = `✅ ${res.file}（${(res.size / 1024).toFixed(0)} KB）`;
    const player = $("#tts-player");
    player.src = res.url + "&t=" + Date.now();
    player.classList.remove("hidden");
    player.play().catch(() => {});
    loadOutputs();
  } catch (e) {
    box.className = "result err";
    box.textContent = "合成失败：" + e.message;
  }
  busy(btn, false);
}

async function loadOutputs() {
  try {
    const { outputs } = await api("/api/outputs");
    const ul = $("#outputs");
    if (!outputs.length) {
      ul.innerHTML = `<li class="dim">还没有产出</li>`;
    } else {
      ul.innerHTML = outputs.map((o) => `
        <li>
          <span class="grow">${esc(o.name)} ${outputBadge(o.name)}</span>
          <span class="dim">${(o.size / 1024).toFixed(0)} KB</span>
          <button class="mini" data-out="${esc(o.name)}">播放</button>
          <button class="mini" data-aba="${esc(o.name)}">设为A</button>
          <button class="mini" data-abb="${esc(o.name)}">设为B</button>
        </li>`).join("");
      ul.querySelectorAll("[data-out]").forEach((b) =>
        b.addEventListener("click", () =>
          window.open("/api/outputs/file?name=" + encodeURIComponent(b.dataset.out), "_blank")));
      ul.querySelectorAll("[data-aba]").forEach((b) =>
        b.addEventListener("click", () => setAB("a", b.dataset.aba)));
      ul.querySelectorAll("[data-abb]").forEach((b) =>
        b.addEventListener("click", () => setAB("b", b.dataset.abb)));
    }
  } catch (e) { /* ignore */ }
}


/* 产出类型徽章 / 音色专属色 / 快捷键 / 状态记忆 */

function outputBadge(name) {
  if (name.includes("翻唱成品")) return `<span class="obadge sing">翻唱成品</span>`;
  if (name.includes("换声")) return `<span class="obadge conv">换声干声</span>`;
  if (name.includes("原曲")) return `<span class="obadge conv">分离</span>`;
  return `<span class="obadge tts">语音</span>`;
}

function hueOf(name) {
  let h = 0;
  for (const c of String(name)) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

function fmtDur(sec) {
  if (!isFinite(sec)) return "";
  const s = Math.round(sec % 60), m = Math.floor(sec / 60);
  return m + ":" + String(s).padStart(2, "0");
}

/* ---------------- 🧬 素材 ---------------- */

async function showMaterials() {
  const v = currentVoice();
  const ul = $("#mat-list");
  const enrollBtn = $("#mt-enroll");
  if (!v) {
    ul.innerHTML = `<li class="dim">还没有音色：先去「🎧 发现」获得一个，素材会存在它的名下</li>`;
    $("#mt-count").textContent = "";
    enrollBtn.classList.add("hidden");
    return;
  }
  try {
    const { materials } = await api("/api/materials?voice=" + encodeURIComponent(v.name));
    const total = materials.reduce((s, m) => s + m.size, 0);
    $("#mt-count").textContent = materials.length ? `${materials.length} 条 · ${(total / 1024 / 1024).toFixed(2)} MB` : "（空）";
    if (!materials.length) {
      ul.innerHTML = `<li class="dim">还没有素材：点下方「一键补 3 条」或上传</li>`;
    } else {
      ul.innerHTML = materials.map((m) => `
        <li>
          <span class="grow">${esc(m.name)}</span>
          <span class="mdur" data-dur="${esc(m.name)}"></span>
          <span class="dim">${(m.size / 1024 / 1024).toFixed(2)} MB</span>
          <button class="mini" data-play="${esc(m.name)}">试听</button>
        </li>`).join("");
      ul.querySelectorAll("[data-play]").forEach((b) =>
        b.addEventListener("click", () =>
          window.open(`/api/materials/file?voice=${encodeURIComponent(v.name)}&name=${encodeURIComponent(b.dataset.play)}`, "_blank")));
      // 探测时长
      materials.forEach((m) => {
        const a = new Audio();
        a.preload = "metadata";
        a.src = `/api/materials/file?voice=${encodeURIComponent(v.name)}&name=${encodeURIComponent(m.name)}`;
        a.addEventListener("loadedmetadata", () => {
          const el = ul.querySelector(`[data-dur="${CSS.escape(m.name)}"]`);
          if (el) el.textContent = fmtDur(a.duration);
        });
      });
    }
    enrollBtn.classList.toggle("hidden", v.provider === "fish" || v.provider === "kits");
  } catch (e) {
    ul.innerHTML = `<li class="dim">加载失败: ${esc(e.message)}</li>`;
  }
}

async function loadMaterialSourceVoices() {
  try {
    const { voices } = await api("/api/voices");
    const sel = $("#gm-source");
    const usable = voices.filter((v) => (v.status || "ready") !== "failed" && v.provider !== "kits");
    sel.innerHTML = usable.length
      ? usable.map((v) => `<option value="${esc(v.name)}">${esc(v.name)}（${esc(v.provider)}）</option>`).join("")
      : `<option value="">（先造一个音色：凭空造或用现成的）</option>`;
  } catch (e) { /* ignore */ }
}

async function generateMaterial(text, btn, label) {
  const v = currentVoice();
  if (!v) return toast("先在右上选择音色", false);
  const source = $("#gm-source").value;
  if (!source) return toast("没有源音色：先「＋新建音色」造一个（凭空造或官方音色）", false);
  busy(btn, true, label);
  try {
    const r = await api("/api/materials/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice_name: v.name, source_voice: source, rate: 1.0 }),
    });
    return r;
  } catch (e) {
    toast("生成失败: " + e.message, false);
    return null;
  } finally {
    busy(btn, false);
  }
}

async function runGenerateOne() {
  const text = $("#gm-text").value.trim();
  if (!text) return toast("请填写生成文本", false);
  const r = await generateMaterial(text, $("#gm-run"), "生成中…");
  if (r) {
    toast(`素材已生成：${r.material}（${(r.size / 1024).toFixed(0)} KB）`);
    showMaterials();
  }
}

async function runAutoFill() {
  const btn = $("#gm-auto");
  const v = currentVoice();
  if (!v) return toast("先在右上选择音色", false);
  for (let i = 0; i < AUTO_TEXTS.length; i++) {
    const r = await generateMaterial(AUTO_TEXTS[i], btn, `生成中 ${i + 1}/3…`);
    if (!r) return;
    showMaterials();
  }
  toast("✅ 已补 3 条素材（约45秒），够克隆了！可点上方「注册正式音色」");
}

async function uploadAll(btn) {
  const v = currentVoice();
  if (!v) return toast("先在右上选择音色", false);
  const files = Array.from(($("#mat-file").files) || []);
  if (!files.length) return toast("请选择音频文件", false);
  let ok = 0, fail = 0;
  for (let i = 0; i < files.length; i++) {
    busy(btn, true, `上传中 ${i + 1}/${files.length}`);
    try {
      const res = await fetch(`/api/materials/upload?voice=${encodeURIComponent(v.name)}`, {
        method: "POST", body: files[i],
        headers: { "X-Filename": encodeURIComponent(files[i].name) },
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
      ok++;
    } catch (e) { fail++; toast(`${files[i].name} 上传失败: ${e.message}`, false); }
  }
  busy(btn, false);
  if (ok) toast(`入库成功 ${ok} 个${fail ? `，失败 ${fail} 个` : ""}`);
  $("#mat-file").value = "";
  showMaterials();
}

async function runEnroll() {
  const v = currentVoice();
  if (!v) return toast("先选择音色", false);
  const provider = $("#mt-enroll-provider").value || "bailian";
  ensureProvider(provider, () => doEnroll(v.name, provider));
}

async function doEnroll(name, provider) {
  const btn = $("#mt-enroll");
  busy(btn, true, "注册中…（10~60秒）");
  const box = $("#mt-enroll-result");
  box.className = "result"; box.classList.remove("hidden");
  box.textContent = `正在用素材在 ${provider} 注册正式音色…`;
  try {
    const res = await api("/api/voices/enroll", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice_name: name, provider }),
    });
    const e2 = res.voice;
    box.className = "result ok";
    box.textContent = `✅ 注册成功：${e2.name}（voice_id: ${e2.voice_id}）\n去 🎤 说话试试！`;
    toast("音色注册成功");
    loadVoices();
  } catch (e) {
    box.className = "result err";
    box.textContent = "注册失败：" + e.message;
  }
  busy(btn, false);
}

/* ---------------- 🎧 声音大厅 ---------------- */

let hallAll = [];
let hallSelected = null;
let hallModel = "";
let hallProviderMap = {};

async function loadHall() {
  const grid = $("#hall-grid");
  try {
    const [hallRes, provRes] = await Promise.all([api("/api/hall"), api("/api/providers")]);
    hallProviderMap = Object.fromEntries(provRes.providers.map((p) => [p.id, p.configured]));
    hallAll = hallRes.voices || [];
    // 模型下拉：只列有音色目录的；已接入排前，默认选中第一个已接入的
    const modelIds = [...new Set(hallAll.map((v) => v.provider))];
    const order = modelIds.sort((a, b) => (hallProviderMap[b] ? 1 : 0) - (hallProviderMap[a] ? 1 : 0));
    const nameOf = (pid) => (hallAll.find((v) => v.provider === pid) || {}).provider_name || pid;
    $("#hall-model").innerHTML = order.map((pid) =>
      `<option value="${esc(pid)}">${esc(nameOf(pid))}${hallProviderMap[pid] ? " · 已接入" : " · 未接入"}</option>`).join("");
    hallModel = order.find((pid) => hallProviderMap[pid]) || order[0] || "";
    if (hallModel) $("#hall-model").value = hallModel;
    fillHallStyle(hallAll.filter((v) => !hallModel || v.provider === hallModel));
    updateHallHint();
    renderHall();
  } catch (e) {
    grid.innerHTML = `<p class="hint">大厅加载失败：${esc(e.message)}</p>`;
  }
}

function renderHall() {
  const q = $("#hall-q").value.trim().toLowerCase();
  const gender = $("#hall-gender").value;
  const style = $("#hall-style").value;
  const list = hallAll.filter((v) => {
    if (hallModel && v.provider !== hallModel) return false;
    if (gender && !(v.tags || []).includes(gender)) return false;
    if (style && !(v.tags || []).includes(style)) return false;
    if (q) {
      const hay = (v.name + " " + (v.tags || []).join(" ") + " " + v.provider_name).toLowerCase();
      if (!hay.includes(q.toLowerCase())) return false;
    }
    return true;
  });
  const grid = $("#hall-grid");
  if (!list.length) {
    grid.innerHTML = `<p class="hint">该模型下没有匹配的声音——换个分类或清空搜索试试。</p>`;
    return;
  }
  grid.innerHTML = list.map((v) => {
    const hue = hueOf(v.voice_id);
    const initial = (v.name || "?").slice(0, 1);
    const meta = esc(JSON.stringify({ provider: v.provider, voice_id: v.voice_id, target_model: v.target_model || "", name: v.name, provider_name: v.provider_name, tags: v.tags, free_preview: !!v.free_preview, official_demo: !!v.official_demo }));
    const canPreview = (hallProviderMap[v.provider]) || v.free_preview;
    const badge = canPreview
      ? `<span class="obadge tts">✅ 可试听${(!hallProviderMap[v.provider]) ? "·样音" : ""}</span>`
      : `<span class="obadge sing">🔑 待接入</span>`;
    const selCls = hallSelected && hallSelected.voice_id === v.voice_id && hallSelected.provider === v.provider ? " hall-selected" : "";
    return `
    <div class="voicecard${selCls}" data-hselect='${meta}'>
      <div class="vhead">
        <span class="avatar" style="background:hsl(${hue},55%,42%)">${esc(initial)}</span>
        <div><b>${esc(v.name)}</b><div class="dim">${esc(v.provider_name)}</div></div>
      </div>
      <div>${(v.tags || []).map((t) => `<span class="obadge tts" style="margin:2px 4px 2px 0">${esc(t)}</span>`).join("")}${badge}</div>
      <div class="actions">
        <button data-hpreview='${meta}'>▶ 试听</button>
        <button class="primary" data-huse='${meta}'>用她说话</button>
      </div>
    </div>`;
  }).join("");
  grid.querySelectorAll("[data-hselect]").forEach((card) =>
    card.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      selectHallVoice(JSON.parse(card.dataset.hselect));
    }));
  grid.querySelectorAll("[data-hpreview]").forEach((b) =>
    b.addEventListener("click", () => {
      const info = JSON.parse(b.dataset.hpreview);
      selectHallVoice(info);
      runHallPreview(b);
    }));
  grid.querySelectorAll("[data-huse]").forEach((b) =>
    b.addEventListener("click", async () => {
      const info = JSON.parse(b.dataset.huse);
      let name = info.name.split("（")[0].trim() || "我的音色";
      let i = 2;
      while (state.voices.some((v) => v.name === name)) name = `${info.name.split("（")[0].trim()}_${i++}`;
      try {
        await api("/api/voices/manual", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ voice_name: name, provider: info.provider, voice_id: info.voice_id, target_model: info.target_model }),
        });
        toast(`「${name}」已登记，去说话吧`);
        setCurrentAndRefresh(name);
      } catch (e) { toast("登记失败: " + e.message, false); }
    }));
}

function updateHallHint() {
  const hint = $("#hall-model-hint");
  if (!hallModel) { hint.hidden = true; return; }
  if (hallProviderMap[hallModel]) {
    hint.hidden = true;
  } else {
    hint.hidden = false;
    hint.innerHTML = `⚠ 该模型还未接入——点「▶ 试听」会引导你接入（填一次 Key 即可），或先试已接入的模型。`;
  }
}

async function onHallModelChange() {
  hallModel = $("#hall-model").value;
  hallSelected = null;
  resetHallSelection();
  fillHallStyle(hallAll.filter((v) => v.provider === hallModel));
  updateHallHint();
  renderHall();
}

/* 清空「当前选中」的展示（切换模型 / 重置时用；风格条常驻，不再整体隐藏） */
function resetHallSelection() {
  const name = $("#hall-sel-name"), src = $("#hall-sel-src"), av = $("#hall-sel-avatar");
  if (name) name.textContent = "未选择";
  if (src) src.textContent = "点下方卡片选中一个音色";
  if (av) { av.style.background = ""; av.textContent = "?"; }
  document.querySelectorAll("#hall-grid .voicecard").forEach((c) => c.classList.remove("hall-selected"));
}

function selectHallVoice(info) {
  hallSelected = info;
  $("#hall-sel-name").textContent = info.name;
  $("#hall-sel-src").textContent = info.provider_name || "";
  const hue = hueOf(info.voice_id);
  const av = $("#hall-sel-avatar");
  av.style.background = `hsl(${hue},55%,42%)`;
  av.textContent = (info.name || "?").slice(0, 1);
  document.querySelectorAll("#hall-grid .voicecard").forEach((c) => {
    try {
      const d = JSON.parse(c.dataset.hselect);
      c.classList.toggle("hall-selected", d.voice_id === info.voice_id && d.provider === info.provider);
    } catch (err) {}
  });
}

async function runHallPreview(btn) {
  if (!hallSelected) return toast("先点一张音色卡选中", false);
  const doOnce = async () => {
    const text = ($("#hall-text").value || "").trim().slice(0, 100);
    if (!text) return toast("请填试听文字", false);
    busy(btn, true, "合成中…");
    try {
      const res = await api("/api/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: hallSelected.provider,
          voice_id: hallSelected.voice_id,
          target_model: hallSelected.target_model || "",
          text,
        }),
      });
      const p = $("#hall-player");
      p.src = res.url + "&t=" + Date.now();
      p.classList.remove("hidden");
      p.play().catch(() => {});
    } catch (e) { throw e; }
    busy(btn, false);
  };
  const doPreview = async () => {
    try {
      await doOnce();
    } catch (e) {
      // Edge 免费接口偶发 403/慢响应（DRM 窗口边界），自动重试一次
      try {
        await doOnce();
      } catch (e2) { toast("试听失败: " + e2.message, false); busy(btn, false); }
    }
  };
  if (!hallProviderMap[hallSelected.provider]) {
    if (hallSelected.free_preview) {
      await doPreview();
      toast("已播放官方样音；接入该模型后可自定义文字试听");
      return;
    }
    ensureProvider(hallSelected.provider, doPreview);
    return;
  }
  await doPreview();
}

/* ---------------- 🎵 翻唱 ---------------- */

async function loadCover() {
  const box = $("#cover-check");
  const engine = ($("#sc-engine") || {}).value || "local-svc";
  const st = state.status || await api("/api/status").catch(() => null);
  if (!st) { box.textContent = "状态获取失败"; return; }
  const prov = (st.providers || []).find((p) => p.id === engine);
  const voices = state.voices.filter((v) => v.provider === engine && v.status !== "failed");
  const lines = [];
  if (engine === "local-svc") {
    lines.push(prov && prov.configured
      ? "✅ 本地 Seed-VC 已就绪（demucs 分离 + Seed-VC 换声，全程免费）"
      : `❌ 还没配置本地 Seed-VC 目录 <button class="mini" data-local-setup="1">去设置</button>`);
    lines.push("ℹ 本机 CPU 跑：整曲约 3~10 分钟，步数低更快");
    lines.push(voices.length
      ? `✅ 本地参考音色 ${voices.length} 个`
      : `⚠ 没有本地参考音色：造声音 → 登记已有 → 来源选「本地 Seed-VC」，voice_id 填参考音频路径（10~30 秒干声）`);
  } else {
    lines.push(prov && prov.configured
      ? "✅ Kits.AI 已配置"
      : `❌ 未配置 Kits.AI Key（需订阅） <button class="mini" data-kits-setup="1">立即接入</button>`);
    lines.push(st.ffmpeg
      ? "✅ ffmpeg 已安装（任意格式自动混音）"
      : "⚠ 未装 ffmpeg：wav 可直混；mp3 伴奏需安装 ffmpeg");
    lines.push(voices.length
      ? `✅ 歌手音色 ${voices.length} 个`
      : `⚠ 没有歌手音色：在 kits.ai 用多段唱歌素材训练后，点 <button class="mini" data-kits-voice="1">登记歌手音色</button>`);
  }
  box.innerHTML = lines.join("<br>");
  $("#cover-form").classList.toggle("hidden", !(prov && prov.configured));
  const sel = $("#sc-voice");
  sel.innerHTML = voices.map((v) => `<option value="${esc(v.name)}">${esc(v.name)}</option>`).join("")
    || `<option value="">（无可用音色）</option>`;
}

function renderCoverVoices() { loadCover(); }

async function runSing() {
  const btn = $("#sc-run");
  const file = ($("#sc-file").files || [])[0];
  if (!file) return toast("请选歌曲/干声文件", false);
  const voice = $("#sc-voice").value;
  if (!voice) return toast("没有歌手音色：按上方清单先登记", false);
  const mode = $("#sc-mode").value;
  const engine = ($("#sc-engine") || {}).value || "local-svc";
  const params = new URLSearchParams({
    voice_name: voice,
    strength: $("#sc-strength").value || "0.8",
    pitch_shift: $("#sc-pitch").value || "0",
    engine: engine,
  });
  busy(btn, true, "处理中…");
  const prog = $("#sc-progress");
  const start = Date.now();
  const localNote = engine === "local-svc" ? "本地处理中" : "云端处理中";
  const estNote = engine === "local-svc" ? "通常 3~10 分钟（CPU）" : "通常 1~5 分钟";
  const timer = setInterval(() => {
    prog.textContent = `${localNote}… 已 ${Math.round((Date.now() - start) / 1000)} 秒（分离 → 换声 → 混音，${estNote}）`;
  }, 1000);
  const box = $("#sc-result");
  box.className = "result"; box.classList.remove("hidden");
  box.textContent = "任务已提交，等待云端完成…";
  try {
    const res = await fetch(`/api/kits/${mode}?${params}`, {
      method: "POST", body: file,
      headers: { "X-Filename": encodeURIComponent(file.name) },
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
    box.className = "result ok";
    const player = $("#sc-player");
    if (mode === "sing") {
      box.textContent = `✅ 翻唱完成（${data.voice} × ${data.song}）\n成品: ${data.final || "未混音（缺伴奏或 ffmpeg，可下载干声+伴奏手动合成）"}\n换声干声: ${data.converted}` + (data.backing ? `\n原曲伴奏: ${data.backing}` : "");
      if (data.final_url) {
        player.src = data.final_url + "&t=" + Date.now();
        player.classList.remove("hidden");
        player.play().catch(() => {});
      }
    } else {
      box.textContent = `✅ 换声完成（${data.voice}）\n文件: ${data.path}`;
      player.src = data.url + "&t=" + Date.now();
      player.classList.remove("hidden");
      player.play().catch(() => {});
    }
    loadOutputs();
  } catch (e) {
    box.className = "result err";
    box.textContent = "失败：" + e.message;
  }
  clearInterval(timer);
  prog.textContent = "";
  busy(btn, false);
}

/* ---------------- 模型接入（按需引导） ---------------- */

let _providersCache = null;
async function getProviders(force) {
  if (!_providersCache || force) {
    const res = await api("/api/providers");
    _providersCache = res.providers;
  }
  return _providersCache;
}

function fieldHtml(pid, f, cur) {
  const val = cur[f.key] || "";
  const isSecret = !!f.secret;
  const shown = isSecret ? "" : val;
  const ph = isSecret
    ? (val ? `已保存（${val}），留空则不修改` : (f.placeholder || ""))
    : (f.placeholder || "");
  return `<label>${esc(f.label)}<input data-fk="${esc(f.key)}"
    type="${isSecret ? "password" : "text"}" value="${esc(shown)}" placeholder="${esc(ph)}" autocomplete="off"></label>` +
    (f.help ? `<p class="hint" style="margin:-4px 0 8px">${esc(f.help)}</p>` : "");
}

async function renderProviderForm(pid, mount, onDone) {
  const providers = await getProviders();
  const p = providers.find((x) => x.id === pid);
  if (!p) { mount.innerHTML = `<p class="hint">未知模型</p>`; return; }
  const cfg = await api("/api/config");
  const cur = (cfg.providers && cfg.providers[pid]) || {};
  mount.innerHTML = p.config_schema.map((f) => fieldHtml(pid, f, cur)).join("") +
    `<button class="primary" data-psave="${esc(pid)}">保存并继续</button>`;
  mount.querySelector("[data-psave]").addEventListener("click", async (e) => {
    const values = {};
    mount.querySelectorAll("input[data-fk]").forEach((inp) => {
      if (inp.value.trim()) values[inp.dataset.fk] = inp.value.trim();
    });
    if (!Object.keys(values).length) return toast("没有要保存的配置", false);
    e.target.disabled = true;
    await saveProvider(pid, values, p.display_name);
    _providersCache = null;
    mount.innerHTML = "";
    if (onDone) onDone();
  });
}

/* 按需引导：未配置时弹出该模型（且只有它）的接入表单，保存后继续原操作 */
async function ensureProvider(pid, onDone) {
  const providers = await getProviders(true);
  const p = providers.find((x) => x.id === pid);
  if (!p) return;
  if (p.configured) { onDone(); return; }
  $("#po-title").textContent = `接入 ${p.display_name}`;
  $("#po-sub").textContent = `使用 ${p.display_name} 前需要先配置——只填这一家，填完自动继续。`;
  await renderProviderForm(pid, $("#po-body"), async () => {
    $("#prooverlay").classList.add("hidden");
    onDone();
  });
  $("#prooverlay").classList.remove("hidden");
}

async function renderProviderRows() {
  const providers = await getProviders(true);
  const box = $("#provider-rows");
  const rows = providers.filter((p) => !p.id.startsWith("custom:") || p.configured);
  box.innerHTML = rows.map((p) => {
    const dot = p.configured ? '<span class="pdot ok"></span>' : '<span class="pdot bad"></span>';
    const tag = p.id.startsWith("custom:") ? ' <span class="obadge conv">自定义</span>' : "";
    const del = p.id.startsWith("custom:")
      ? ` <button class="mini" data-pdel="${esc(p.id)}">删除</button>` : "";
    const btn = p.configured
      ? `<button class="mini" data-pedit="${esc(p.id)}">编辑</button>${del}`
      : `<button class="mini" data-pedit="${esc(p.id)}">接入</button>`;
    return `<div class="prow">
      <div class="grow">${dot}<b>${esc(p.display_name)}</b>${tag}</div>
      <div>${btn}</div>
    </div>`;
  }).join("");
}

async function openAddPanel(tabName, preselect) {
  $("#addmodel-panel").hidden = false;
  const builtin = tabName !== "custom";
  $("#amtab-builtin").classList.toggle("primary", builtin);
  $("#amtab-custom").classList.toggle("primary", !builtin);
  $("#am-hint").textContent = builtin
    ? "从内置目录中选择模型，填入其 API 密钥即可使用。"
    : "连接中转站、自建服务或其他兼容 OpenAI 协议的语音接口：填 API 地址（到 /v1 这一级）、协议和密钥。";
  $("#am-builtin").hidden = !builtin;
  $("#am-custom").hidden = builtin;
  if (builtin) {
    const providers = await getProviders();
    const list = providers.filter((p) => !p.id.startsWith("custom:"));
    $("#add-provider").innerHTML = list.map((p) =>
      `<option value="${esc(p.id)}">${esc(p.display_name)}${p.configured ? "（已接入）" : ""}</option>`).join("");
    if (preselect) $("#add-provider").value = preselect;
    renderProviderForm($("#add-provider").value, $("#provider-form"), renderProviderRows);
  } else {
    renderCustomForm($("#custom-form"));
  }
}

let customMode = "openai"; // openai（简） | advanced（高级 JSON）

async function renderCustomForm(mount) {
  customMode = "openai";
  mount.innerHTML = `
    <label>接口风格<select id="cp-style">
      <option value="openai">OpenAI 风格（大多数聚合平台与自建服务）</option>
      <option value="advanced">高级（自定义请求头与请求体 JSON）</option>
    </select></label>
    <div id="cp-simple">
      <div class="row">
        <label>API 地址（填到 /v1 这一级，路径自动补）<input id="cp-base" placeholder="https://api.example.com/v1"></label>
        <label>API 协议<select id="cp-protocol">
          <option value="openai_speech">OpenAI 语音合成（POST base/audio/speech）</option>
          <option value="endpoint">完整端点 URL（base 当完整地址用）</option>
        </select></label>
      </div>
      <div class="row">
        <label>模型名<input id="cp-model" placeholder="tts-1"></label>
        <label>音色 ID<input id="cp-voice" placeholder="alloy"></label>
      </div>
      <div class="row">
        <label>API Key<input id="cp-key" type="password" autocomplete="off" placeholder="不需要鉴权就留空"></label>
        <label>输出格式<input id="cp-ext" value="wav"></label>
      </div>
      <div class="row">
        <label>显示名<input id="cp-name" placeholder="留空自动取域名"></label>
      </div>
    </div>
    <div id="cp-adv" hidden>
      <div class="row">
        <label>标识 id<input id="cp-id" placeholder="mytts"></label>
        <label>显示名<input id="cp-name2" placeholder="我的TTS"></label>
      </div>
      <div class="row">
        <label>API Key（可空）<input id="cp-key2" type="password" autocomplete="off"></label>
        <label>输出格式<input id="cp-ext2" value="wav"></label>
      </div>
      <label>接口 URL<input id="cp-url2" placeholder="https://api.example.com/v1/audio/speech"></label>
      <label>请求头 JSON<textarea id="cp-headers" rows="3">{"Authorization": "Bearer {{api_key}}"}</textarea></label>
      <label>请求体 JSON<textarea id="cp-body" rows="6">{"model": "tts-1", "input": "{{text}}", "voice": "{{voice_id}}", "response_format": "wav"}</textarea></label>
      <div class="row">
        <label>音频响应位置<select id="cp-from"><option value="binary">二进制响应体</option><option value="output.audio.data">JSON 路径（base64）</option></select></label>
        <label>固定音色 ID<input id="cp-voice2" placeholder="alloy"></label>
      </div>
    </div>
    <button id="cp-save" class="primary">保存自定义模型</button>
    <p class="hint" id="cp-hint">OpenAI 风格会自动生成请求头与请求体，只填地址、模型名、音色即可；更特殊的接口切「高级」手写 JSON。占位符：<code>{{api_key}}</code> <code>{{text}}</code> <code>{{voice_id}}</code></p>`;
  $("#cp-style").addEventListener("change", (e) => {
    customMode = e.target.value;
    $("#cp-simple").hidden = customMode !== "openai";
    $("#cp-adv").hidden = customMode !== "advanced";
  });
  $("#cp-save").addEventListener("click", saveCustom);
}

async function saveProvider(provider, values, label) {
  try {
    await api("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, values }),
    });
    toast(`${label} 配置已保存`);
    loadStatus();
  } catch (e) { toast("保存失败: " + e.message, false); }
}

async function saveCustom() {
  const btn = $("#cp-save");
  if (customMode === "openai") {
    // 简模式：自动生成请求头/请求体
    const protocol = $("#cp-protocol").value;
    const addr = $("#cp-base").value.trim();
    if (!addr) return toast("请填 API 地址", false);
    let host = "custom";
    try { host = new URL(addr).hostname; } catch (e) { /* ignore */ }
    const id = host.replace(/[^a-z0-9-]/gi, "").slice(0, 20) || "custom";
    const ext = ($("#cp-ext").value.trim() || "wav").toLowerCase();
    const values = {
      display_name: $("#cp-name").value.trim() || host,
      voice_id: $("#cp-voice").value.trim() || "alloy",
      ext,
      headers: { Authorization: "Bearer {{api_key}}" },
      body: {
        model: $("#cp-model").value.trim() || "tts-1",
        input: "{{text}}",
        voice: $("#cp-voice").value.trim() || "alloy",
        response_format: ext,
      },
      audio_from: "binary",
    };
    if (protocol === "openai_speech") { values.base = addr; values.protocol = "openai_speech"; }
    else { values.url = addr; values.protocol = "endpoint"; }
    const key = $("#cp-key").value.trim();
    if (key) values.api_key = key;
    busy(btn, true, "保存中…");
    await saveProvider("custom:" + id, values, values.display_name);
    busy(btn, false);
    renderProviderRows();
    return;
  }
  // 高级模式：手写 JSON
  const id = ($("#cp-id").value || "").trim().replace(/[^A-Za-z0-9_-]/g, "");
  if (!id) return toast("请填自定义模型标识 id", false);
  let headers, body;
  try { headers = JSON.parse($("#cp-headers").value || "{}"); }
  catch (e) { return toast("请求头不是合法 JSON", false); }
  try { body = JSON.parse($("#cp-body").value || "{}"); }
  catch (e) { return toast("请求体不是合法 JSON", false); }
  const values = {
    display_name: $("#cp-name2").value.trim() || id,
    url: $("#cp-url2").value.trim(),
    headers, body,
    audio_from: $("#cp-from").value,
    voice_id: $("#cp-voice2").value.trim(),
    ext: ($("#cp-ext2").value.trim() || "wav").toLowerCase(),
  };
  if (!values.url) return toast("请填接口 URL", false);
  const key = $("#cp-key2").value.trim();
  if (key) values.api_key = key;
  busy(btn, true, "保存中…");
  await saveProvider("custom:" + id, values, "自定义模型");
  busy(btn, false);
  renderProviderRows();
}

/* ---------------- 启动 ---------------- */

/* ---------------- 启动 ---------------- */

/* ---------------- 启动 ---------------- */

/* ---------------- 启动 ---------------- */

/* ---------------- 启动 ---------------- */

/* ---------------- 启动 ---------------- */

/* ---------------- 启动 ---------------- */

/* ---------------- 启动 ---------------- */

function wire() {
  // 空值安全绑定：元素不存在时静默跳过（某元素删除不会中断后续绑定）
  const on = (sel, ev, fn) => { const el = $(sel); if (el) el.addEventListener(ev, fn); };
  // 侧边导航
  $$("#side-nav button, .side-foot button").forEach((b) =>
    b.addEventListener("click", () => switchTask(b.dataset.task)));
  // 顶栏
  on("#cur-voice", "change", (e) => {
    state.current = e.target.value;
    try { localStorage.setItem("shenglai.voice", state.current); } catch (err) {}
    renderCurrent();
    toast("已切换到「" + state.current + "」");
  });
  // 发现：造声音
  $$(".wizintent").forEach((b) => b.addEventListener("click", () => switchIntent(b.dataset.intent)));
  on("#vd-run", "click", runDesign);
  on("#vd-provider", "change", syncDesignProvider);
  syncDesignProvider();
  on("#qc-run", "click", runClone);
  on("#pk-refresh", "click", loadPickCatalog);
  on("#pk-register", "click", registerPick);
  // 说话
  on("#tts-text", "keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runTTS(); });
  on("#out-refresh", "click", loadOutputs);
  document.querySelectorAll("[data-gohall]").forEach((b) =>
    b.addEventListener("click", () => switchTask("hall")));
  // 大厅
  on("#hall-model", "change", onHallModelChange);
  on("#hall-q", "input", renderHall);
  on("#hall-gender", "change", renderHall);
  on("#hall-style", "change", renderHall);
  // 我的：素材
  on("#gm-auto", "click", runAutoFill);
  on("#gm-run", "click", runGenerateOne);
  on("#mat-file", "change", () => uploadAll($("#mat-file")));
  on("#mt-enroll", "click", runEnroll);
  // 翻唱
  on("#sc-run", "click", runSing);
  on("#sc-reload", "click", loadCover);
  on("#sc-engine", "change", loadCover);
  on("#cover-check", "click", (e) => {
    if (e.target.closest("[data-local-setup]")) switchTask("settings");
    if (e.target.closest("[data-kits-setup]")) ensureProvider("kits", loadCover);
    if (e.target.closest("[data-kits-voice]")) {
      switchTask("create");
      switchIntent("pick");
      $("#pk-provider").value = "kits";
      loadPickCatalog();
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  });
  // 模型接入
  on("#btn-addmodel", "click", () => openAddPanel("builtin"));
  on("#amtab-builtin", "click", () => openAddPanel("builtin"));
  on("#amtab-custom", "click", () => openAddPanel("custom"));
  on("#add-provider", "change", () =>
    renderProviderForm($("#add-provider").value, $("#provider-form"), renderProviderRows));
  on("#provider-rows", "click", async (e) => {
    const edit = e.target.closest("[data-pedit]");
    if (edit) {
      const pid = edit.dataset.pedit;
      if (pid.startsWith("custom:")) openAddPanel("custom");
      else openAddPanel("builtin", pid);
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    const del = e.target.closest("[data-pdel]");
    if (del) {
      const pid = del.dataset.pdel;
      await saveProvider(pid, { api_key: "", url: "" }, pid);
      renderProviderRows();
    }
  });
  on("#po-cancel", "click", () => $("#prooverlay").classList.add("hidden"));
  // 全局委托兜底：关键动作按钮（防任何绑定丢失）
  document.addEventListener("click", (e) => {
    try {
      const el = e.target.closest("#hall-run");
      if (el) { runHallPreview(el); return; }
      const sp = e.target.closest("#tts-run");
      if (sp) { runTTS(); return; }
      const nb = e.target.closest("#btn-new");
      if (nb) { switchTask("create"); switchIntent("design"); }
    } catch (err) {
      console.error("[声来]", err);
      toast("操作出错: " + err.message, false);
    }
  });
  // 素材拖拽
  const drop = $("#drop");
  if (drop) {
    ["dragenter", "dragover"].forEach((ev) =>
      drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
    ["dragleave", "drop"].forEach((ev) =>
      drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
    drop.addEventListener("drop", (e) => {
      if (e.dataTransfer && e.dataTransfer.files.length) {
        $("#mat-file").files = e.dataTransfer.files;
        toast("已选 " + e.dataTransfer.files.length + " 个文件，自动上传中…");
        uploadAll($("#mat-file"));
      }
    });
  }
}

(async function init() {
  try { wire(); } catch (e) { window.__WIRE_ERR = e.stack || e.message; }

  await loadStatus();
  await loadVoices();
  switchTask(state.voices.length ? "speak" : "hall");
  loadMaterialSourceVoices();
  loadCloneModels();
  loadOutputs();
})();
