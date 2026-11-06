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
      const isCur = state.current === v.name;
      return `
      <div class="voicecard${isCur ? " hall-selected" : ""}" data-name="${esc(v.name)}">
        <div class="vhead">
          <span class="avatar" style="background:hsl(${hue},55%,42%)">${esc(initial)}</span>
          <div><b>${esc(v.name)}</b> ${isCur ? '<span class="obadge tts">🟢 当前音色</span>' : `<span class="dim">${esc(v.status || "ready")}</span>`}</div>
        </div>
        <div class="dim">${esc(v.provider || "待注册")} · ${esc(v.voice_id || "-")}</div>
        <div class="dim">模型: ${esc(v.target_model || "默认")} · 素材 ${(v.materials || []).length} 个</div>
        <div class="actions">
          ${isCur ? "" : `<button class="primary" data-setcur="${esc(v.name)}">设为当前</button>`}
          <button data-try="${esc(v.name)}">去说话</button>
          <button data-del="${esc(v.name)}">删除</button>
        </div>
      </div>`;
    }).join("");
    box.querySelectorAll("[data-setcur]").forEach((b) =>
      b.addEventListener("click", async () => {
        state.current = b.dataset.setcur;
        try { localStorage.setItem("shenglai.voice", state.current); } catch (err) {}
        await api("/api/voices/current", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: state.current }),
        }).catch(() => {});
        renderVoices();
        renderCurrent();
        toast(`已启动「${state.current}」——发语音就用这个声音`);
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
  overview: "总览", mine: "我的音色", hall: "免费音色", create: "自由造音",
  cover: "翻唱", settings: "模型接入", guide: "使用指南",
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
  if (name === "hall") { loadHall().then(() => warmCurrent()); loadOutputs(); }
  if (name === "create") { renderVoices(); loadCloneModels(); }
  if (name === "mine") { renderVoices(); showMaterials(); loadMaterialSourceVoices(); }
  if (name === "cover") loadCover();
  if (name === "overview") { renderUsage(); renderOverview(); }
  if (name === "settings") { renderProviderRows(); renderLocalModules(); }
}

/* ---------------- 📊 总览页（资产/引擎/平台一览） ---------------- */

async function renderOverview() {
  const assets = $("#ov-assets"), engines = $("#ov-engines"), platforms = $("#ov-platforms");
  if (!assets) return;
  const st = state.status || await api("/api/status").catch(() => null);
  const voiceCount = state.voices.filter((v) => (v.status || "ready") !== "failed").length;
  const cur = state.current || "（未设置）";
  if (assets) {
    assets.innerHTML = `<div class="mine-row">
      <div class="lmrow" style="padding:6px 0"><b>${voiceCount}</b> 个音色 · 当前使用「<b>${esc(cur)}</b>」</div>
      <div class="lmrow" style="padding:6px 0">素材库：D:\\AI\\声音工坊\\materials\\</div>
    </div>`;
  }
  try {
    const lm = await api("/api/local-modules");
    if (engines) {
      engines.innerHTML = (lm.modules || []).map((m) => {
        const dot = m.installed ? '<span class="pdot ok"></span>' : '<span class="pdot bad"></span>';
        return `<div class="ov-line">${dot}<b>${esc(m.name)}</b>
          <span class="dim">${m.installed ? "已安装" : "未安装"}${m.detail && m.installed ? ` · ${esc(m.detail)}` : ""}</span></div>`;
      }).join("");
    }
  } catch (e) { if (engines) engines.innerHTML = `<p class="hint">本地引擎状态获取失败</p>`; }
  if (platforms) {
    const provs = (st && st.providers) || [];
    platforms.innerHTML = provs.map((p) => {
      const dot = p.configured ? '<span class="pdot ok"></span>' : '<span class="pdot bad"></span>';
      return `<div class="ov-line">${dot}<b>${esc(p.display_name)}</b>
        <span class="dim">${p.configured ? "已接入" : "未接入"}${p.tier ? ` · ${esc(p.tier)}` : ""}</span></div>`;
    }).join("");
  }
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
  switchTask("hall");
  if (first) toast("🎉 第一个音色就绪！已切到「免费音色」，点音色卡让它开口吧");
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
    text: $("#hall-text").value,
    voice_name: v.name,
    emotion: ($("#tts-emotion") || {}).value || "默认",
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
    // 显示上限：超过 20 条不再撑长页面，列表变固定高度滚轮
    ul.classList.toggle("capped", outputs.length >= 20);
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
let hallPreviewSeq = 0; // 试听序号：防止快速切换音色时旧的慢请求把新的播放结果顶掉
let hallProviders = []; // 全量供应商（含 capabilities）：跨平台复刻目标列表用
let hallModel = "";
let hallProviderMap = {};

async function loadHall() {
  const grid = $("#hall-grid");
  try {
    const [hallRes, provRes] = await Promise.all([api("/api/hall"), api("/api/providers")]);
    hallProviderMap = Object.fromEntries(provRes.providers.map((p) => [p.id, p.configured]));
    hallProviders = provRes.providers || [];
    hallAll = hallRes.voices || [];
    // 模型下拉：只列有音色目录的；已接入排前，默认选中第一个已接入的
    const modelIds = [...new Set(hallAll.map((v) => v.provider))];
    const order = modelIds.sort((a, b) => (hallProviderMap[b] ? 1 : 0) - (hallProviderMap[a] ? 1 : 0));
    const nameOf = (pid) => (hallAll.find((v) => v.provider === pid) || {}).provider_name || pid;
    const tierOf = (pid) => {
      const meta = provRes.providers.find((x) => x.id === pid);
      return meta && meta.tier ? `【${meta.tier}】` : "";
    };
    $("#hall-model").innerHTML = order.map((pid) =>
      `<option value="${esc(pid)}">${tierOf(pid)}${esc(nameOf(pid))}${hallProviderMap[pid] ? " · 已接入" : " · 未接入"}</option>`).join("");
    // 默认选中：第一个「已接入且 Key 有效」的（第一次打开不该看到一屏 Key 失效）；
    // 全都失效时退回第一个已接入的（如实显示失效徽标）
    const keyOk = (pid) => (hallAll.find((v) => v.provider === pid) || {}).key_ok !== false;
    hallModel = order.find((pid) => hallProviderMap[pid] && keyOk(pid))
      || order.find((pid) => hallProviderMap[pid])
      || order[0] || "";
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
    // 有搜索词时跨全部模型搜索；否则按选中模型过滤
    if (q) {
      const hay = (v.name + " " + (v.tags || []).join(" ") + " " + v.provider_name).toLowerCase();
      if (!hay.includes(q.toLowerCase())) return false;
    } else if (hallModel && v.provider !== hallModel) {
      return false;
    }
    if (gender && !(v.tags || []).includes(gender)) return false;
    if (style && !(v.tags || []).includes(style)) return false;
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
    const meta = esc(JSON.stringify({ provider: v.provider, voice_id: v.voice_id, target_model: v.target_model || "", name: v.name, provider_name: v.provider_name, tags: v.tags, free_preview: !!v.free_preview, official_demo: !!v.official_demo, key_ok: (v.key_ok === undefined ? null : v.key_ok) }));
    const canPreview = (hallProviderMap[v.provider] && v.key_ok !== false) || v.free_preview;
    const keyInvalid = !!hallProviderMap[v.provider] && v.key_ok === false;
    const badge = keyInvalid
      ? `<span class="obadge sing">⚠️ Key 失效</span>`
      : canPreview
        ? `<span class="obadge tts">✅ 可试听${(!hallProviderMap[v.provider]) ? "·样音" : ""}</span>`
        : `<span class="obadge sing">🔑 待接入</span>`;
    const selCls = hallSelected && hallSelected.voice_id === v.voice_id && hallSelected.provider === v.provider ? " hall-selected" : "";
    return `
    <div class="voicecard${selCls}" data-hselect='${meta}'>
      <div class="vhead">
        <span class="avatar" style="background:hsl(${hue},55%,42%)">${esc(initial)}</span>
        <div><b>${esc(v.name)}</b><div class="dim">${esc(v.provider_name)}${v.official_demo ? " · 官方样音" : ""}</div></div>
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
      const info = JSON.parse(card.dataset.hselect);
      selectHallVoice(info);
      // 切换音色即自动试听：直接用输入框里的文字（命中缓存秒开，进度条就在上方预览栏里）。
      // Key 失效的模型只选中（不弹引导不空转报错）；未接入且无样音的也只选中——想接再点「▶ 试听」。
      if ((hallProviderMap[info.provider] && info.key_ok !== false) || info.free_preview) runHallPreview($("#hall-run"));
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
        // 设为 TTS 输出默认：/api/speak 不带 voice 参数时就用她（QQ 机器人跟随这个）
        await api("/api/voices/current", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        }).catch(() => {});
        // 试听（官方样音录音，免费）≠ 发语音（实时合成，要 Key）——登记时就说清，别让人用的时候才发现
        let warn = "";
        if (info.key_ok === false) {
          warn = ` ⚠️ 但发语音需要${info.provider_name}的 Key（当前失效）——想免费发语音，选小米 MiMo 的音色`;
        } else if (!hallProviderMap[info.provider]) {
          warn = ` ⚠️ 试听听到的是官方样音录音（免费）；正式发语音需要接入${info.provider_name}并填 Key——想现在就能发，选小米 MiMo 的音色`;
        }
        toast(`「${name}」已登记并设为 TTS 输出音色。${warn}`, !!warn);
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
  // 来源行直接说清"正式合成用哪家的 Key、现在能不能用"
  const keyState = info.key_ok === false ? " · Key ❌ 失效，去模型接入页重贴"
    : info.key_ok === true ? " · Key ✅ 合成可用"
    : info.free_preview ? "" : " · 未接入（点试听会引导填 Key）";
  $("#hall-sel-src").textContent = (info.provider_name || "") + keyState;
  // 跨平台复刻目标：有克隆能力（enroll 注册式或 clone 直传式）+ 已接入 + Key 未失效的其他平台
  const ccSel = $("#hall-cc-target");
  if (ccSel) {
    const keyOf = (pid) => (hallAll.find((x) => x.provider === pid) || {}).key_ok;
    const targets = (hallProviders || []).filter((p) => {
      const caps = p.capabilities || [];
      const clonable = caps.includes("enroll") || caps.includes("clone");
      return clonable && caps.includes("tts") && p.configured
        && p.id !== info.provider && keyOf(p.id) !== false;
    });
    ccSel.innerHTML = targets.map((p) =>
      `<option value="${esc(p.id)}">${esc(p.display_name.split("（")[0])}</option>`).join("");
    ccSel.classList.toggle("hidden", !targets.length);
    const run = $("#hall-cc-run");
    if (run) run.classList.toggle("hidden", !targets.length);
  }
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
  const seq = ++hallPreviewSeq; // 快速连点多个音色时，只让最后一次的结果真正播放
  const doOnce = async () => {
    const text = ($("#hall-text").value || "").trim().slice(0, 100);
    if (!text) return toast("请填试听文字", false);
    busy(btn, true, "…");
    try {
      const cache = await api("/api/preview-cache?provider=" + encodeURIComponent(hallSelected.provider) +
        "&voice_id=" + encodeURIComponent(hallSelected.voice_id) +
        "&text=" + encodeURIComponent(text));
      let url;
      if (cache.cached || cache.official_demo) {
        url = cache.url;
      } else {
        const res = await api("/api/preview", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: hallSelected.provider, voice_id: hallSelected.voice_id,
            target_model: hallSelected.target_model || "", text }),
        });
        url = res.url;
      }
      if (seq !== hallPreviewSeq) { busy(btn, false); return; } // 已经切到别的音色了，丢弃这次过期结果
      const p = $("#hall-player");
      // 缓存戳只拼给内部链接（/api/preview-file?name=X 本来就带 ?）；
      // 阿里官方样音是外链且无查询参数，拼 &t= 会变成非法 URL（404 XML → Format error）
      p.src = /^https?:/i.test(url) ? url : url + "&t=" + Date.now();
      p.classList.remove("hidden");
      p.play().catch(() => {});
    } catch (e) { throw e; }
    busy(btn, false);
  };
  const runWithRetry = async () => {
    try {
      await doOnce();
    } catch (e) {
      try { await doOnce(); }
      catch (e2) { toast("试听失败: " + e2.message, false); busy(btn, false); }
    }
  };
  // 有官方样音的音色（free_preview）无需接入即可试听；其余模型才弹接入引导
  if (!hallProviderMap[hallSelected.provider] && !hallSelected.free_preview) {
    ensureProvider(hallSelected.provider, runWithRetry);
    return;
  }
  await runWithRetry();
}

async function warmCurrent() {
  try {
    await fetch("/api/warm-previews?provider=" + encodeURIComponent(hallModel || ""), { method: "POST" });
  } catch (e) { /* 预热失败不影响使用 */ }
}

/* ---------------- 🧩 本地引擎模块（翻唱引擎的一键安装管理） ---------------- */

let lmTimer = null;

async function renderLocalModules() {
  const box = $("#local-modules");
  if (!box) return;
  const { modules } = await api("/api/local-modules").catch(() => ({ modules: [] }));
  box.innerHTML = modules.map((m) => {
    const dot = m.installed ? '<span class="pdot ok"></span>' : '<span class="pdot bad"></span>';
    const running = m.status === "running" || m.status === "cancelling";
    const showBar = running || m.status === "done" || m.status === "error";
    const btn = running
      ? `<button class="mini" data-lm-cancel="${esc(m.id)}">取消</button>`
      : (!m.installed && m.installable ? `<button class="mini" data-lm-install="${esc(m.id)}">一键安装</button>` : "");
    // 已安装的手动部署型（Seed-VC）：给「复制目录」方便定位；没有安装按钮是因为已经装好了
    const copyDir = (m.installed && m.dir)
      ? `<button class="mini" data-lm-copy="${esc(m.dir)}">复制目录</button>` : "";
    const uninst = (m.installed && m.id === "rvc" && !running)
      ? `<button class="mini" data-lm-uninstall="${esc(m.id)}">卸载</button>` : "";
    const dirField = (!m.installed && m.installable && m.id === "rvc")
      ? `<label style="display:block;margin:8px 0 0;font-size:12px">安装到目录<input class="lm-dir" value="${esc(m.dir || "")}" style="width:100%;margin:4px 0 0"></label>` : "";
    const bar = showBar
      ? `<div class="lm-bar"><div class="lm-bar-in${m.status === "error" ? " err" : ""}" style="width:${m.pct || 0}%"></div></div>`
      : "";
    const detail = (running || m.status === "done" || m.status === "error") && m.detail
      ? `<div class="dim" ${m.status === "error" ? 'style="color:#ffb0b0"' : ""}>${esc(m.detail)}</div>` : "";
    const stateLine = m.installed || running || m.status === "done" || m.status === "error"
      ? `<div class="dim">${m.installed && !running && m.status !== "done" ? "状态：" : ""}${esc(m.detail || (m.installed ? "已安装" : ""))}</div>` : "";
    return `<div class="prow lmrow">
      <div class="grow">${dot}<b>${esc(m.name)}</b> <span class="obadge conv">${esc(m.deploy)}</span>
        <div class="dim">${esc(m.compute)} · ${esc(m.size)}</div>
        <div class="dim">${esc(m.desc)}</div>
        ${dirField}${stateLine}${bar}${detail}
      </div>
      <div>${btn}${copyDir}${uninst}</div>
    </div>`;
  }).join("");
  box.querySelectorAll("[data-lm-copy]").forEach((b) =>
    b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(b.dataset.lmCopy); toast("目录路径已复制"); }
      catch (err) { toast(b.dataset.lmCopy); }
    }));
  box.querySelectorAll("[data-lm-install]").forEach((b) =>
    b.addEventListener("click", async () => {
      b.disabled = true; b.textContent = "启动中…";
      const dir = b.closest(".lmrow")?.querySelector(".lm-dir")?.value?.trim() || "";
      try {
        const r = await api("/api/local-modules/install", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: b.dataset.lmInstall, dir }),
        });
        if (!r.ok) { toast(r.error || "无法启动安装", false); b.disabled = false; b.textContent = "一键安装"; }
      } catch (e) { toast("启动失败: " + e.message, false); b.disabled = false; b.textContent = "一键安装"; }
      renderLocalModules();
    }));
  box.querySelectorAll("[data-lm-uninstall]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (b.dataset.armed !== "1") {
        b.dataset.armed = "1"; b.dataset.orig = b.textContent;
        b.textContent = "确认卸载?"; b.style.borderColor = "#ff6b6b";
        setTimeout(() => { if (b.isConnected && b.dataset.armed === "1") { b.dataset.armed = ""; b.textContent = b.dataset.orig; b.style.borderColor = ""; } }, 3000);
        return;
      }
      b.disabled = true; b.textContent = "卸载中…";
      try {
        const r = await api("/api/local-modules/uninstall", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: b.dataset.lmUninstall }),
        });
        toast(r.message || (r.ok ? "已卸载" : "卸载失败"), r.ok !== false);
      } catch (e) { toast("卸载失败: " + e.message, false); }
      renderLocalModules();
    }));
  box.querySelectorAll("[data-lm-cancel]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api("/api/local-modules/cancel", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: b.dataset.lmCancel }),
      }).catch(() => {});
      renderLocalModules();
    }));
  const anyRunning = modules.some((m) => m.status === "running" || m.status === "cancelling");
  if (anyRunning) { clearTimeout(lmTimer); lmTimer = setTimeout(renderLocalModules, 1500); }
}

/* ---------------- 📊 用量统计（本地记账，DeepSeek 风格柱状图） ---------------- */

async function renderUsage() {
  const head = $("#usage-head"), chart = $("#usage-chart"), daysEl = $("#usage-days"), note = $("#usage-note");
  if (!chart) return;
  const data = await api("/api/usage").catch(() => null);
  if (!data) { chart.innerHTML = '<p class="hint">用量数据加载失败</p>'; return; }
  const days = data.days || [];
  const maxChars = Math.max(...days.map((d) => d.chars), 1);
  head.innerHTML = `
    <span><div class="lab">今日合成</div><b>${data.today.count}</b> 次</span>
    <span><div class="lab">今日字数</div><b>${data.today.chars}</b></span>
    <span><div class="lab">14 天累计</div><b>${data.total.chars}</b> 字 / ${data.total.count} 次</span>
    <span><div class="lab">14 天预估费用</div><b>¥${(data.total.cost || 0).toFixed(2)}</b></span>`;
  chart.innerHTML = days.map((d) => {
    const h = Math.max(2, Math.round(d.chars / maxChars * 118));
    const tips = Object.entries(d.providers || {}).map(([p, c]) => `${p}: ${c} 字`).join("；");
    const cls = d.chars ? "usage-bar" : "usage-bar zero";
    return `<div class="usage-col" title="${d.date}｜${d.count} 次｜${tips || "无合成"}${d.cost ? `｜约 ¥${d.cost}` : ""}">
      <div class="${cls}" style="height:${h}px"></div></div>`;
  }).join("");
  daysEl.innerHTML = days.map((d) => `<span>${d.date}</span>`).join("");
  const prices = data.prices || {};
  const set = Object.entries(prices).map(([p, v]) => `${p}=${v}元/千字`).join("、");
  note.textContent = set
    ? `费用为估算（单价：${set}）；改单价：D:\\AI\\声音工坊\\config.json 的 usage_prices（元/千字符）`
    : "未设单价——只统计量。想估算费用：config.json 加 usage_prices（如 {\"bailian\": 0.2} = 每千字 0.2 元）";
}

/* ---------------- 🎵 翻唱 ---------------- */

async function loadCover() {
  const box = $("#cover-check");
  const engine = ($("#sc-engine") || {}).value || "local-svc";
  const st = state.status || await api("/api/status").catch(() => null);
  if (!st) { box.textContent = "状态获取失败"; return; }
  const prov = (st.providers || []).find((p) => p.id === engine);
  const voices = state.voices.filter((v) => v.provider === engine && v.status !== "failed");
  const localProv = (st.providers || []).find((p) => p.id === "local-svc");
  const localVoices = state.voices.filter((v) => v.provider === "local-svc" && v.status !== "failed");
  const kitsProv = (st.providers || []).find((p) => p.id === "kits");
  const lines = [];
  // 引擎状态胶囊 = 引擎切换器：点哪个切哪个，当前高亮
  const chip = (cur, txt, engId) =>
    `<span class="statuschip enginechip${cur ? " eng-cur" : ""}" data-eng="${engId}" title="点击切换引擎">${txt}${cur ? " · 当前引擎" : " · 点击切换"}</span>`;
  lines.push(chip(engine === "local-svc",
    localProv && localProv.configured
      ? `✅ 本地 Seed-VC（免费·零训练）：就绪${localVoices.length ? ` · 参考音色 ${localVoices.length} 个` : ""}`
      : "❌ 本地 Seed-VC：未配置目录",
    "local-svc"));
  lines.push(chip(engine === "kits",
    kitsProv && kitsProv.configured ? "✅ Kits.AI（付费·多素材训练）：已配置" : "◻ Kits.AI（付费·多素材训练）：未配置",
    "kits"));
  if (engine === "local-svc") {
    // 参考音色为空时下拉里已显示「(无可用音色)」，不再额外堆提示小字
  } else {
    lines.push(st.ffmpeg
      ? "✅ ffmpeg 已安装（任意格式自动混音）"
      : "⚠ 未装 ffmpeg：wav 可直混；mp3 伴奏需安装 ffmpeg");
    lines.push(voices.length
      ? `✅ 歌手音色 ${voices.length} 个`
      : `⚠ 没有歌手音色：在 kits.ai 用多段唱歌素材训练后，点 <button class="mini" data-kits-voice="1">登记歌手音色</button>`);
  }
  box.innerHTML = lines.map((l) => `<span class="statuschip">${l}</span>`).join("");
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
    // 已配置的加「测试」：零成本在线校验 Key，贴完立刻知道行不行（不再等到合成失败才发现）
    const test = p.configured ? ` <button class="mini" data-pverify="${esc(p.id)}">测试</button>` : "";
    const tierTag = p.tier ? `<span class="obadge conv">${esc(p.tier)}</span> ` : "";
    return `<div class="prow">
      <div class="grow">${dot}<b>${esc(p.display_name)}</b>${tag} ${tierTag}
        <div class="pvout-wrap"><span class="dim" data-pvout></span></div>
      </div>
      <div>${btn}${test}</div>
    </div>`;
  }).join("");
  box.querySelectorAll("[data-pverify]").forEach((b) =>
    b.addEventListener("click", async () => {
      const pid = b.dataset.pverify;
      const out = b.closest(".prow").querySelector("[data-pvout]");
      b.disabled = true; b.textContent = "测试中…";
      if (out) out.textContent = "";
      try {
        const r = await api("/api/verify-key", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: pid }),
        });
        if (out) {
          out.textContent = r.message || (r.ok ? "✅" : "❌");
          out.style.color = r.ok === true ? "var(--ok, #7ee2a8)" : r.ok === false ? "#ffb0b0" : "";
        }
        if (r.ok === false) toast(r.message || "Key 无效", false);
      } catch (e) {
        if (out) { out.textContent = "测试失败"; out.style.color = "#ffb0b0"; }
        toast("测试失败: " + e.message, false);
      }
      b.disabled = false; b.textContent = "测试";
    }));
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
  // 关闭 = 只关浏览器标签页；面板进程保留在后台（127.0.0.1:17878 随时回来）
  on("#btn-quit", "click", () => {
    try { window.close(); } catch (err) {}
    setTimeout(() => {
      if (!window.closed) {
        document.body.innerHTML =
          '<div style="display:flex;height:100vh;align-items:center;justify-content:center;flex-direction:column;gap:14px;' +
          'font:15px system-ui;color:#6b7280;background:#fff">' +
          '<div style="font-size:44px">🎙️</div><div style="font-size:18px;color:#111827">声来仍在后台运行</div>' +
          '<div style="font-size:13px">直接关闭这个标签页即可；再次访问 127.0.0.1:17878 随时回来</div></div>';
      }
    }, 300);
  });
  on("#cur-voice", "change", (e) => {
    state.current = e.target.value;
    try { localStorage.setItem("shenglai.voice", state.current); } catch (err) {}
    renderCurrent();
    // 同步到服务端：/api/speak 不带 voice 参数时用她（QQ 机器人跟随这个）
    api("/api/voices/current", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: e.target.value }),
    }).catch(() => {});
    toast("已切换到「" + state.current + "」");
  });
  // 左下角更新提示：发现 git 新版本 → 一键更新（fetch+checkout+自动重启）
  let updateDismissed = false;
  async function checkUpdate() {
    if (updateDismissed) return;
    const r = await api("/api/update-check").catch(() => null);
    if (!r || !r.has_update) return;
    const b = $("#update-banner");
    if (!b || !b.classList.contains("hidden")) return;
    $("#update-text").textContent = `🚀 发现新版本 v${r.latest}（当前 v${r.local}）`;
    b.classList.remove("hidden");
  }
  on("#update-go", "click", async () => {
    const btn = $("#update-go"), txt = $("#update-text");
    btn.disabled = true; btn.textContent = "更新中…";
    txt.textContent = "正在拉取新版本并重启面板…（约 10 秒）";
    const r = await api("/api/update", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }).catch((e) => ({ ok: false, error: e.message }));
    if (!r.ok) {
      txt.textContent = "更新失败：" + (r.error || "未知原因");
      btn.disabled = false; btn.textContent = "重试";
      return;
    }
    txt.textContent = r.message || "更新完成，面板重启中…";
    // 轮询等新面板起来（旧进程退出 → 中转拉起新面板），然后刷新拿新前端
    let tries = 0;
    const poll = setInterval(async () => {
      tries++;
      try {
        await fetch("/api/status", { cache: "no-store" });
        clearInterval(poll);
        location.reload();
      } catch (err) {
        if (tries > 20) { clearInterval(poll); txt.textContent = "重启超时——请手动刷新页面"; }
      }
    }, 2000);
  });
  on("#update-skip", "click", () => {
    updateDismissed = true;
    $("#update-banner").classList.add("hidden");
  });
  checkUpdate();
  setInterval(checkUpdate, 5 * 60 * 1000);
  // 发现：造声音
  $$(".wizintent").forEach((b) => b.addEventListener("click", () => switchIntent(b.dataset.intent)));
  on("#vd-run", "click", runDesign);
  on("#vd-provider", "change", syncDesignProvider);
  syncDesignProvider();
  on("#qc-run", "click", runClone);
  on("#pk-refresh", "click", loadPickCatalog);
  on("#pk-register", "click", registerPick);
  // 说话
  on("#hall-cc-run", "click", async () => {
    if (!hallSelected) return toast("先选一张音色卡", false);
    const target = ($("#hall-cc-target") || {}).value;
    if (!target) return toast("没有可用的复刻目标平台（需要有克隆能力且 Key 就绪）", false);
    const btn = $("#hall-cc-run");
    busy(btn, true, "复刻中…");
    try {
      const r = await api("/api/cross-clone", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: hallSelected.provider, voice_id: hallSelected.voice_id, target }),
      });
      toast(`✅ 已复刻为「${r.name}」（素材：${r.src}），立即可发语音`);
      setCurrentAndRefresh(r.name);
    } catch (e) { toast("复刻失败: " + e.message, false); }
    busy(btn, false);
  });
  on("#hall-text", "keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runTTS(); });
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
    const engChip = e.target.closest("[data-eng]");
    if (engChip) {
      const sel = $("#sc-engine");
      if (sel && sel.value !== engChip.dataset.eng) {
        sel.value = engChip.dataset.eng;
        loadCover();
        toast("已切换引擎");
      }
      return;
    }
    if (e.target.closest("[data-use-local]")) {
      const sel = $("#sc-engine");
      if (sel) { sel.value = "local-svc"; }
      loadCover();
      toast("已切到免费本地引擎（Seed-VC）");
      return;
    }
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
      // 滚到表单（在页面中部，不在顶部）+ 描边高亮——"点了没反馈"就是这么来的
      setTimeout(() => {
        const panel = $("#addmodel-panel");
        if (panel && !panel.hidden) {
          panel.scrollIntoView({ behavior: "smooth", block: "center" });
          panel.style.outline = "2px solid var(--accent)";
          panel.style.borderRadius = "10px";
          setTimeout(() => { panel.style.outline = ""; }, 1800);
        }
      }, 100);
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
  switchTask("overview"); // 落地页 = 第一页「总览」
  loadMaterialSourceVoices();
  loadCloneModels();
  loadOutputs();
})();
