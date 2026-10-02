"use strict";

/* ---------------- 默认示例 ---------------- */
const DEFAULTS = {
  duration: 10,
  maxRamp: 20,
  zones: [
    { name: "A区", initial_temp: 20, alpha1: "0.20", alpha2: "0.35",
      final_low: 140, final_high: 160, upper_limit: 200,
      exposure_threshold: 100, exposure_min: "300.00" },
    { name: "B区", initial_temp: 25, alpha1: "0.15", alpha2: "0.25",
      final_low: 120, final_high: 140, upper_limit: 180,
      exposure_threshold: 90, exposure_min: "200.00" },
  ],
};

const ZONE_FIELDS = [
  ["initial_temp", "初温（℃，整数 0~300）", "number", 0, 300, 1],
  ["alpha1", "响应系数 α₁（0.01~1.00，两位小数）", "text", null, null, null],
  ["alpha2", "响应系数 α₂（0.01~1.00，两位小数）", "text", null, null, null],
  ["upper_limit", "全程温度上限（℃，0~300 整数）", "number", 0, 300, 1],
  ["final_low", "终温区间下限（℃，整数）", "number", 0, 300, 1],
  ["final_high", "终温区间上限（℃，整数）", "number", 0, 300, 1],
  ["exposure_threshold", "热暴露阈值（℃，0~300 整数）", "number", 0, 300, 1],
  ["exposure_min", "最低累计热暴露（≥0，两位小数）", "text", null, null, null],
];

let lastResult = null;
let lastRequest = null;

/* ---------------- 构造区卡片 ---------------- */
function buildZoneCards() {
  document.querySelectorAll(".zone-card").forEach((card, zi) => {
    card.innerHTML = "";
    const title = document.createElement("h2");
    title.textContent = `② 第 ${zi + 1} 区参数`;
    card.appendChild(title);

    const row = document.createElement("div");
    row.className = "zone-title-row";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.id = `z${zi}_name`;
    nameInput.maxLength = 20;
    nameInput.value = DEFAULTS.zones[zi].name;
    row.appendChild(nameInput);
    card.appendChild(row);

    const grid = document.createElement("div");
    grid.className = "grid grid-4";
    for (const [key, label, type, min, max, step] of ZONE_FIELDS) {
      const lab = document.createElement("label");
      lab.textContent = label;
      const inp = document.createElement("input");
      inp.type = type;
      inp.id = `z${zi}_${key}`;
      inp.value = DEFAULTS.zones[zi][key];
      if (min !== null) { inp.min = min; inp.max = max; inp.step = step; }
      lab.appendChild(inp);
      grid.appendChild(lab);
    }
    card.appendChild(grid);
  });
}

/* ---------------- 锁定分钟输入 ---------------- */
function renderLocks(preserve = {}) {
  const area = document.getElementById("locksArea");
  area.innerHTML = "";
  const n = parseInt(document.getElementById("duration").value, 10);
  for (let t = 1; t <= (isNaN(n) ? 0 : n); t++) {
    const lab = document.createElement("label");
    lab.textContent = `第 ${t} 分钟 U(${t})`;
    const inp = document.createElement("input");
    inp.type = "number";
    inp.min = 0; inp.max = 300; inp.step = 1;
    inp.id = `lock_${t}`;
    inp.placeholder = "不锁定";
    if (preserve[t] !== undefined) inp.value = preserve[t];
    lab.appendChild(inp);
    area.appendChild(lab);
  }
}

/* ---------------- 读取与校验 ---------------- */
function readAlpha(id, label, errs) {
  const el = document.getElementById(id);
  const v = el.value.trim();
  // 至多两位小数；数值范围 0.01~1.00（1、1.0、1.00 均等于 1.00）
  const n = Number(v);
  if (!/^\d+(\.\d{1,2})?$/.test(v) || !(n >= 0.01 && n <= 1)) {
    errs.push(`${label} 必须是 0.01~1.00 之间、至多两位小数`);
    el.classList.add("bad");
    return v;
  }
  el.classList.remove("bad");
  return v;
}

function readInt(id, label, lo, hi, errs) {
  const el = document.getElementById(id);
  const v = el.value.trim();
  const n = Number(v);
  if (!/^-?\d+$/.test(v) || n < lo || n > hi) {
    errs.push(`${label} 必须是 ${lo}~${hi} 的整数`);
    el.classList.add("bad");
    return null;
  }
  el.classList.remove("bad");
  return n;
}

function readDecimal(id, label, errs) {
  const el = document.getElementById(id);
  const v = el.value.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(v)) {
    errs.push(`${label} 必须是非负数、至多两位小数`);
    el.classList.add("bad");
    return v;
  }
  el.classList.remove("bad");
  return v;
}

function collectRequest() {
  const errs = [];
  const duration = readInt("duration", "烘烤时长", 1, 24, errs);
  const maxRamp = readInt("maxRamp", "最大跃变", 0, 300, errs);

  const zones = [];
  for (let zi = 0; zi < 2; zi++) {
    const z = {
      name: document.getElementById(`z${zi}_name`).value.trim() || `区${zi + 1}`,
      initial_temp: readInt(`z${zi}_initial_temp`, `${zi + 1}区初温`, 0, 300, errs),
      alpha1: readAlpha(`z${zi}_alpha1`, `${zi + 1}区α₁`, errs),
      alpha2: readAlpha(`z${zi}_alpha2`, `${zi + 1}区α₂`, errs),
      upper_limit: readInt(`z${zi}_upper_limit`, `${zi + 1}区上限`, 0, 300, errs),
      final_low: readInt(`z${zi}_final_low`, `${zi + 1}区终温下限`, 0, 300, errs),
      final_high: readInt(`z${zi}_final_high`, `${zi + 1}区终温上限`, 0, 300, errs),
      exposure_threshold: readInt(`z${zi}_exposure_threshold`, `${zi + 1}区阈值`, 0, 300, errs),
      exposure_min: readDecimal(`z${zi}_exposure_min`, `${zi + 1}区最低累计热暴露`, errs),
    };
    if (z.final_low !== null && z.final_high !== null && z.final_low > z.final_high) {
      errs.push(`${zi + 1}区终温区间下限不得大于上限`);
    }
    zones.push(z);
  }

  const locks = [];
  if (duration !== null) {
    for (let t = 1; t <= duration; t++) {
      const el = document.getElementById(`lock_${t}`);
      if (el && el.value.trim() !== "") {
        const n = Number(el.value.trim());
        if (!Number.isInteger(n) || n < 0 || n > 300) {
          errs.push(`第 ${t} 分钟锁定值必须是 0~300 整数`);
          el.classList.add("bad");
        } else {
          el.classList.remove("bad");
          locks.push({ minute: t, value: n });
        }
      }
    }
  }

  showError(errs.join("\n"));
  if (errs.length) return null;
  return { duration, max_ramp: maxRamp, locks, zones };
}

function showError(msg) {
  const box = document.getElementById("formError");
  if (msg) { box.textContent = msg; box.classList.remove("hidden"); }
  else box.classList.add("hidden");
}

/* ---------------- 渲染结果 ---------------- */
function marginCell(v) {
  if (v === null || v === undefined) return '<td class="muted">—</td>';
  const neg = Number(v) < 0;
  return `<td class="${neg ? "neg" : "pos"}">${v}</td>`;
}

function renderResult(result) {
  lastResult = result;
  const sec = document.getElementById("resultSection");
  sec.classList.remove("hidden");

  const banner = document.getElementById("statusBanner");
  const map = {
    FEASIBLE_OPTIMAL: ["optimal", "✓ 已找到可行曲线，并证明为字典序最优（先最小化设定总和，再按分钟序最小化各设定值）"],
    FEASIBLE_NOT_OPTIMAL: ["feasible", "◐ 已找到可行曲线，但 10 秒限时内未能证明最优；下列曲线可用，但可能存在设定总和更小的曲线"],
    NO_FEASIBLE_FOUND: ["none", "× 10 秒限时内尚未找到任何可行曲线（这不等同于无解，可放宽约束后重试）"],
    INFEASIBLE: ["infeasible", "⊘ 无解：在当前参数下不存在任何满足全部约束的曲线"],
    ERROR: ["error", `⚠ 求解错误：${result.reason || "未知错误"}`],
  };
  const [cls, text] = map[result.status] || ["error", result.status_text];
  banner.className = `banner ${cls}`;
  banner.textContent = text;

  const meta = document.getElementById("resultMeta");
  const wrap = document.getElementById("trajectoryWrap");
  wrap.innerHTML = "";

  if (!result.setpoints || !result.setpoints.length) {
    meta.classList.add("hidden");
    return;
  }
  meta.classList.remove("hidden");
  document.getElementById("objSum").textContent = result.objective_sum;
  document.getElementById("elapsed").textContent = `${result.elapsed_ms} ms`;
  document.getElementById("optFlag").textContent = result.optimal ? "已证最优" : "可行 / 未证最优";

  const locked = new Set((lastRequest?.locks || []).map(l => l.minute));
  const n = lastRequest.duration;

  // 汇总表：共享设定温度
  const sum = document.createElement("div");
  sum.className = "traj-block";
  sum.innerHTML = `<h3>共享设定温度 U(t) 与跃变余量</h3>`;
  let html = `<table><thead><tr><th>分钟 t</th><th>设定 U(t)（℃）</th><th>较上一分钟变化 |ΔU|</th><th>跃变余量</th></tr></thead><tbody>`;
  for (let t = 1; t <= n; t++) {
    const u = result.setpoints[t - 1];
    const d = t >= 2 ? Math.abs(result.setpoints[t - 1] - result.setpoints[t - 2]) : null;
    const margin = d === null ? null : lastRequest.max_ramp - d;
    html += `<tr><td>${t}${locked.has(t) ? '<span class="lock-badge">锁</span>' : ""}</td>
      <td>${u}</td>
      <td>${d === null ? '<span class="muted">—</span>' : d}</td>
      ${marginCell(margin)}</tr>`;
  }
  html += `</tbody><tfoot><tr><td>合计</td><td>${result.objective_sum}</td><td colspan="2"></td></tr></tfoot></table>`;
  sum.insertAdjacentHTML("beforeend", html);
  wrap.appendChild(sum);

  // 四条温度轨迹
  for (const tr of result.trajectories) {
    const block = document.createElement("div");
    block.className = "traj-block";
    block.innerHTML = `<h3>${tr.zone} · α = ${tr.alpha} ｜ 终温区间 [${tr.final_low}, ${tr.final_high}] ℃ ｜ 上限 ${tr.upper_limit}℃ ｜ 阈值 ${tr.exposure_threshold}℃</h3>`;
    let t2 = `<table><thead><tr>
      <th>t</th><th>设定 U(t)</th><th>温度 T(t)（℃）</th><th>超标量<br>max(0,T−阈值)</th>
      <th>上限余量<br>上限−T</th><th>终区下余量<br>T−下限</th><th>终区上余量<br>上限−T</th></tr></thead><tbody>`;
    tr.points.forEach(p => {
      t2 += `<tr>
        <td>${p.minute}</td>
        <td>${p.setpoint === null ? '<span class="muted">T(0)初温</span>' : p.setpoint}</td>
        <td>${p.temp}</td>
        <td>${p.excess}</td>
        ${marginCell(p.upper_margin)}
        ${marginCell(p.final_low_margin)}
        ${marginCell(p.final_high_margin)}
      </tr>`;
    });
    const expCls = Number(tr.exposure_margin) < 0 ? "neg" : "pos";
    t2 += `</tbody><tfoot>
      <tr><td colspan="2">热暴露量 E（要求 ≥ ${tr.exposure_min}）</td>
          <td>${tr.exposure}</td>
          <td class="${expCls}">达标余量 ${tr.exposure_margin}</td>
          <td colspan="3"></td></tr>
      </tfoot></table>`;
    block.insertAdjacentHTML("beforeend", t2);
    if (tr.violations && tr.violations.length) {
      block.insertAdjacentHTML("beforeend",
        `<div class="violations">复核告警：${tr.violations.join("；")}</div>`);
    }
    wrap.appendChild(block);
  }

  sec.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------------- API 调用 ---------------- */
async function solve() {
  const req = collectRequest();
  if (!req) return;
  lastRequest = req;
  const btn = document.getElementById("solveBtn");
  btn.disabled = true;
  const timer = document.getElementById("solveTimer");
  const t0 = performance.now();
  timer.textContent = "求解中…（限时 10 秒）";
  try {
    const resp = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    const data = await resp.json();
    if (!resp.ok) {
      const msg = (data.detail || []).map(e =>
        typeof e === "string" ? e : `${e.loc ? e.loc.join(" → ") + "：" : ""}${e.msg}`
      ).join("\n") || `HTTP ${resp.status}`;
      showError(msg);
      document.getElementById("resultSection").classList.add("hidden");
      return;
    }
    showError("");
    renderResult(data);
  } catch (e) {
    showError(`请求失败：${e}`);
  } finally {
    btn.disabled = false;
    timer.textContent = `本次往返耗时 ${Math.round(performance.now() - t0)} ms`;
  }
}

/* ---------------- 快照 ---------------- */
async function saveSnapshot() {
  if (!lastResult || !lastRequest) return;
  const name = prompt("为该快照命名：",
    `试算 ${new Date().toLocaleString("zh-CN", { hour12: false })}`);
  if (!name) return;
  const btn = document.getElementById("saveSnapBtn");
  btn.disabled = true;
  try {
    const resp = await fetch("/api/snapshots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, request: lastRequest, result: lastResult }),
    });
    if (!resp.ok) {
      const data = await resp.json();
      alert("保存失败：" + JSON.stringify(data.detail));
      return;
    }
    await loadSnapshots();
  } finally {
    btn.disabled = false;
  }
}

function statusBadge(s) {
  const map = {
    FEASIBLE_OPTIMAL: ["optimal", "已证最优"],
    FEASIBLE_NOT_OPTIMAL: ["feasible", "可行未证优"],
    NO_FEASIBLE_FOUND: ["none", "超时未找到"],
    INFEASIBLE: ["infeasible", "无解"],
    ERROR: ["error", "错误"],
  };
  const [, t] = map[s] || ["", s];
  return t;
}

async function loadSnapshots() {
  const tbody = document.querySelector("#snapTable tbody");
  tbody.innerHTML = "";
  const resp = await fetch("/api/snapshots");
  const items = await resp.json();
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="muted">暂无快照</td></tr>`;
    return;
  }
  for (const it of items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${it.id}</td><td style="text-align:left">${escapeHtml(it.name)}</td>
      <td>${statusBadge(it.status)}</td>
      <td>${it.optimal === null ? "—" : it.optimal ? "是" : "否"}</td>
      <td>${it.objective_sum === null ? "—" : it.objective_sum}</td>
      <td>${it.elapsed_ms}</td><td>${it.created_at.replace("+00:00", "Z")}</td>
      <td></td>`;
    const td = tr.lastElementChild;
    const loadBtn = document.createElement("button");
    loadBtn.className = "small";
    loadBtn.textContent = "载入";
    loadBtn.onclick = () => loadSnapshot(it.id);
    const delBtn = document.createElement("button");
    delBtn.className = "small";
    delBtn.textContent = "删除";
    delBtn.onclick = async () => {
      if (!confirm(`确定删除快照 #${it.id}？`)) return;
      await fetch(`/api/snapshots/${it.id}`, { method: "DELETE" });
      loadSnapshots();
    };
    td.appendChild(loadBtn);
    td.appendChild(delBtn);
    tbody.appendChild(tr);
  }
}

async function loadSnapshot(id) {
  const resp = await fetch(`/api/snapshots/${id}`);
  const snap = await resp.json();
  const r = snap.payload.request;
  applyRequest(r);
  lastRequest = r;
  renderResult(snap.payload.result);
}

function applyRequest(r) {
  document.getElementById("duration").value = r.duration;
  document.getElementById("maxRamp").value = r.max_ramp;
  renderLocks();
  r.zones.forEach((z, zi) => {
    document.getElementById(`z${zi}_name`).value = z.name;
    document.getElementById(`z${zi}_initial_temp`).value = z.initial_temp;
    document.getElementById(`z${zi}_alpha1`).value = z.alpha1;
    document.getElementById(`z${zi}_alpha2`).value = z.alpha2;
    document.getElementById(`z${zi}_upper_limit`).value = z.upper_limit;
    document.getElementById(`z${zi}_final_low`).value = z.final_low;
    document.getElementById(`z${zi}_final_high`).value = z.final_high;
    document.getElementById(`z${zi}_exposure_threshold`).value = z.exposure_threshold;
    document.getElementById(`z${zi}_exposure_min`).value = z.exposure_min;
  });
  renderLocks(Object.fromEntries((r.locks || []).map(l => [l.minute, l.value])));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------------- 初始化 ---------------- */
function resetDefaults() {
  document.getElementById("duration").value = DEFAULTS.duration;
  document.getElementById("maxRamp").value = DEFAULTS.maxRamp;
  buildZoneCards();
  renderLocks();
  showError("");
}

document.addEventListener("DOMContentLoaded", () => {
  buildZoneCards();
  renderLocks();
  document.getElementById("duration").addEventListener("change", () => {
    const n = parseInt(document.getElementById("duration").value, 10);
    if (n >= 1 && n <= 24) {
      // 保留旧锁定值
      const old = {};
      document.querySelectorAll("#locksArea input").forEach(inp => {
        if (inp.value) old[Number(inp.id.split("_")[1])] = inp.value;
      });
      renderLocks(old);
    }
  });
  document.getElementById("solveBtn").addEventListener("click", solve);
  document.getElementById("resetBtn").addEventListener("click", resetDefaults);
  document.getElementById("saveSnapBtn").addEventListener("click", saveSnapshot);
  document.getElementById("refreshSnapBtn").addEventListener("click", loadSnapshots);
  loadSnapshots();
});
