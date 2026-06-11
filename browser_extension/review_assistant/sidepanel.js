const els = {
  payloadInput: document.getElementById("payloadInput"),
  textReviewBtn: document.getElementById("textReviewBtn"),
  screenshotReviewBtn: document.getElementById("screenshotReviewBtn"),
  serviceUrlInput: document.getElementById("serviceUrlInput"),
  summary: document.getElementById("summary"),
  resultList: document.getElementById("resultList"),
  pageState: document.getElementById("pageState"),
  domCount: document.getElementById("domCount"),
  visionCount: document.getElementById("visionCount"),
  cacheCount: document.getElementById("cacheCount")
};

let reviewPayload = null;
let lastPageHash = "";
let cacheHits = 0;
let debounceTimer = null;
let lastResults = [];
let lastPageSnapshot = {};
let visionCalls = 0;
const visionCache = new Map();
const MAX_VISION_CALLS_PER_PAGE = 3;
const DEFAULT_SERVICE_URL = "http://127.0.0.1:8790";

const TEXT_FIELD_MAP = {
  "计划名称": ["计划名称", "name"],
  "发送渠道": ["发送渠道", "channels"],
  "营销主题": ["营销主题", "theme"],
  "计划区域": ["计划区域", "region"],
  "计划开始时间": ["计划开始时间", "start_time"],
  "计划结束时间": ["计划结束时间", "end_time"],
  "发送时间": ["发送时间", "send_time"],
  "主消费营运区": ["主消费营运区", "main_operating_area"],
  "主消费运营区": ["主消费营运区", "main_operating_area"],
  "执行员工": ["执行员工", "executor_employees"],
  "目标商品编码": ["目标商品编码", "product_codes"],
  "购买目标商品编码": ["目标商品编码", "product_codes"],
  "已领或已使用券规则ID": ["已领或已使用券规则ID", "coupon_ids"],
  "券规则ID": ["已领或已使用券规则ID", "coupon_ids"],
  "员工任务结束时间": ["员工任务结束时间", "step3_end_time"],
  "第3步结束时间": ["员工任务结束时间", "step3_end_time"],
  "短信内容": ["短信内容", "sms_content"],
  "发送内容": ["发送内容", "send_content"],
  "推送内容": ["发送内容", "send_content"],
  "活动介绍": ["活动介绍", "activity_intro"],
  "下发群名": ["社群下发群名", "group_send_name"],
  "社群下发群名": ["社群下发群名", "group_send_name"],
  "社群任务分配方式": ["分配方式", "distribution_mode"],
  "分配方式": ["分配方式", "distribution_mode"],
  "图片数量": ["图片数量", "image_count"]
};

function normText(value) {
  return String(value || "")
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function normComparable(value) {
  return normText(value)
    .replace(/[，,]/g, "、")
    .replace(/\s*、\s*/g, "、")
    .replace(/\s+/g, " ")
    .trim();
}

function compactComparable(value) {
  return normComparable(value).replace(/\s+/g, "");
}

function splitMulti(value) {
  return normComparable(value)
    .split("、")
    .map((x) => x.trim())
    .filter(Boolean);
}

function isMultiField(field) {
  const name = field.name || "";
  const key = field.key || "";
  return /营销主题|主消费营运区|执行员工|目标商品编码|券规则/.test(name) || /theme|area|executor|product|coupon/.test(key);
}

function normalizeDateTime(value) {
  const text = String(value || "");
  const match = text.match(/(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?\s+(\d{1,2})[:：\s](\d{1,2})(?:[:：\s](\d{1,2}))?/);
  if (!match) return "";
  const pad = (x) => String(x || "0").padStart(2, "0");
  return `${match[1]}-${pad(match[2])}-${pad(match[3])} ${pad(match[4])}:${pad(match[5])}:${pad(match[6])}`;
}

function extractDateTimes(value) {
  const text = String(value || "");
  const pattern = /(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?\s+\d{1,2}[:：\s]\d{1,2}(?:[:：\s]\d{1,2})?)/g;
  return Array.from(text.matchAll(pattern)).map((x) => normalizeDateTime(x[1])).filter(Boolean);
}

function isDateTimeField(field) {
  return ["start_time", "end_time", "send_time", "step3_end_time"].includes(field.key || "");
}

function isScopedField(field) {
  return ["main_operating_area", "product_codes", "coupon_ids"].includes(field.key || "");
}

function normalizeChannelText(value) {
  return splitMulti(value).map((item) => {
    const text = compactComparable(item);
    if (/朋友圈|客户朋友圈/.test(text)) return "会员通-发客户朋友圈";
    if (/客户消息|1对1|一对一|会员通群客户消息/.test(text)) return "会员通-发客户消息";
    if (/社群|群发/.test(text)) return "会员通-发送社群";
    if (/短信/.test(text)) return "短信";
    return item;
  }).join("、");
}

function compareDateTimeField(field, expected, actual, pageText) {
  const expectedDt = normalizeDateTime(expected);
  if (!expectedDt) return null;
  const actualDates = extractDateTimes(actual);
  if (actualDates.includes(expectedDt)) {
    return { status: "match", actual: actual || expectedDt, reason: "时间一致" };
  }
  if (actualDates.length) {
    return { status: "mismatch", actual: actualDates.join("、"), reason: "时间不一致" };
  }
  if (field.key !== "step3_end_time") {
    const pageDates = extractDateTimes(pageText);
    if (pageDates.includes(expectedDt)) {
      return { status: "match", actual: expectedDt, reason: "页面可见时间包含目标值" };
    }
  }
  return { status: "unknown", actual: "", reason: "当前页面未读取到该时间字段" };
}

function fieldReviewScope(field) {
  const key = field.key || "";
  if (["main_operating_area", "product_codes", "coupon_ids"].includes(key)) return "请打开第2步目标人群弹窗；弹窗/iframe 可见后插件会自动合并读取";
  if (["image_count"].includes(key)) return "请打开图片/素材区域继续复核";
  return "当前页面未展示，请打开对应步骤或弹窗继续复核";
}

function multiValueMissing(expected, actual) {
  const exp = splitMulti(expected);
  const got = splitMulti(actual);
  const gotCompact = compactComparable(actual);
  return exp.filter((item) => {
    const expCompact = compactComparable(item);
    if (!expCompact) return false;
    if (gotCompact.includes(expCompact)) return false;
    return !got.some((value) => {
      const valueCompact = compactComparable(value);
      return valueCompact.includes(expCompact) || expCompact.includes(valueCompact);
    });
  });
}

function compareField(field, pageValues, pageText) {
  const expected = normText(field.value);
  const actualRaw = pageValues[field.key] || pageValues[field.name] || "";
  const actual = normText(actualRaw);
  if (!expected) return { status: "unknown", actual: "", reason: "原始值为空" };

  if (field.key === "image_count") {
    const expNum = parseInt(expected, 10);
    const gotNum = parseInt(actual || "0", 10);
    if (Number.isFinite(expNum) && gotNum === expNum) return { status: "match", actual: String(gotNum), reason: "图片数量一致" };
    if (actual) return { status: "mismatch", actual: String(gotNum), reason: "图片数量不一致" };
    return { status: "unknown", actual: "", reason: "未读取到图片区域" };
  }

  if (isDateTimeField(field)) {
    const result = compareDateTimeField(field, expected, actual, pageText);
    if (result) return result;
  }

  if (actual) {
    if (field.key === "channels") {
      const exp = splitMulti(normalizeChannelText(expected));
      const got = splitMulti(normalizeChannelText(actual));
      const missing = exp.filter((x) => !got.includes(x));
      if (!missing.length) return { status: "match", actual, reason: "渠道一致" };
      return { status: "mismatch", actual, reason: `渠道缺少: ${missing.join("、")}` };
    }
    if (isMultiField(field)) {
      const missing = multiValueMissing(expected, actual);
      if (!missing.length) return { status: "match", actual, reason: "多值字段一致" };
      return { status: "mismatch", actual, reason: `缺少: ${missing.join("、")}` };
    }
    if (normComparable(actual) === normComparable(expected)) {
      return { status: "match", actual, reason: "字段一致" };
    }
    if (normComparable(actual).includes(normComparable(expected)) || normComparable(expected).includes(normComparable(actual))) {
      return { status: "match", actual, reason: "字段文本包含匹配" };
    }
    return { status: "mismatch", actual, reason: "字段不一致" };
  }

  const pageHaystack = normComparable(pageText);
  const needle = normComparable(expected);
  if (!isScopedField(field) && needle.length >= 4 && pageHaystack.includes(needle)) {
    return { status: "match", actual: expected, reason: "页面可见文本包含目标值" };
  }
  return { status: "unknown", actual: "", reason: fieldReviewScope(field) };
}

function render(results, pageSnapshot) {
  const ok = results.filter((x) => x.status === "match").length;
  const bad = results.filter((x) => x.status === "mismatch").length;
  const unknown = results.filter((x) => x.status === "unknown").length;
  const reviewed = results.filter((x) => x.status !== "unknown");
  const pending = results.filter((x) => x.status === "unknown");
  els.summary.textContent = `已复核 ${reviewed.length}（通过 ${ok}，差异 ${bad}），待打开页面/弹窗继续复核 ${pending.length}。当前页：${pageSnapshot.title || pageSnapshot.url || "未知"}`;
  els.domCount.textContent = String(results.length);
  els.visionCount.textContent = String(visionCalls);
  els.cacheCount.textContent = String(cacheHits);
  const renderItems = (items) => items.map((item) => {
    const label = item.status === "match" ? "一致" : (item.status === "mismatch" ? "差异" : (item.status === "vision" ? "视觉读数" : "待复核"));
    return `
      <div class="item ${item.status}">
        <div class="item-head">
          <span>${escapeHtml(item.name)}</span>
          <span class="badge ${item.status}">${label}</span>
        </div>
        <div class="kv">
          <div class="k">原文</div><div class="v">${escapeHtml(item.expected)}</div>
          <div class="k">页面</div><div class="v">${escapeHtml(item.actual || "未读取到")}</div>
          <div class="k">说明</div><div class="v">${escapeHtml(item.reason)}</div>
        </div>
      </div>`;
  }).join("");
  els.resultList.innerHTML = `
    <div class="group-title">已复核字段</div>
    ${renderItems(reviewed) || '<div class="empty">当前页面暂无已复核字段。</div>'}
    <div class="group-title">待打开页面/弹窗继续复核</div>
    ${renderItems(pending) || '<div class="empty">暂无待复核字段。</div>'}`;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

function normalizeServiceUrl(raw) {
  const value = String(raw || "").trim().replace(/\/+$/, "");
  return value || DEFAULT_SERVICE_URL;
}

function visionEndpoint() {
  const base = normalizeServiceUrl(els.serviceUrlInput.value);
  if (base.endsWith("/api/review/vision")) return base;
  return `${base}/api/review/vision`;
}

async function loadSettings() {
  const data = await chrome.storage.local.get(["reviewServiceUrl"]);
  els.serviceUrlInput.value = data.reviewServiceUrl || DEFAULT_SERVICE_URL;
}

async function saveSettings() {
  const reviewServiceUrl = normalizeServiceUrl(els.serviceUrlInput.value);
  els.serviceUrlInput.value = reviewServiceUrl;
  await chrome.storage.local.set({ reviewServiceUrl });
}

function parseTextPayload(raw) {
  const source = String(raw || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
  if (!source) throw new Error("复核数据为空");
  const rows = {};
  let currentLabel = "";
  let currentKey = "";
  let multiline = false;
  const flush = () => {
    currentLabel = "";
    currentKey = "";
    multiline = false;
  };
  for (const rawLine of source.split("\n")) {
    const line = rawLine.replace(/\s+$/, "");
    const stripped = line.trim();
    if (!stripped || stripped.startsWith("#")) continue;
    if (multiline) {
      const next = stripped.match(/^([^:：]{2,40})\s*[:：]\s*(.*)$/);
      if (!next) {
        rows[currentKey] = [rows[currentKey], line.startsWith("  ") ? line.slice(2) : line]
          .filter(Boolean)
          .join("\n");
        continue;
      }
      flush();
    }
    const match = stripped.match(/^([^:：]{2,40})\s*[:：]\s*(.*)$/);
    if (!match) continue;
    const label = match[1].trim();
    const value = match[2].trim();
    const mapped = TEXT_FIELD_MAP[label];
    if (!mapped) {
      flush();
      continue;
    }
    const key = mapped[1];
    if (value === "|") {
      rows[key] = "";
      currentLabel = label;
      currentKey = key;
      multiline = true;
      continue;
    }
    rows[key] = value;
    flush();
  }
  const expected = [];
  const seen = new Set();
  for (const [label, [name, key]] of Object.entries(TEXT_FIELD_MAP)) {
    if (seen.has(key)) continue;
    seen.add(key);
    const value = normText(rows[key]);
    if (value) expected.push({ name, key, value });
  }
  if (!expected.length) {
    throw new Error("未识别到计划字段，请粘贴 /simple 复核 JSON 或强约束计划文本");
  }
  return {
    version: 1,
    source: "text",
    source_text: source,
    plan_name: rows.name || "",
    expected_fields: expected
  };
}

function parseReviewPayload(raw) {
  const text = String(raw || "").trim();
  if (!text) throw new Error("复核数据为空");
  if (text.startsWith("{")) {
    const payload = JSON.parse(text);
    if (!Array.isArray(payload.expected_fields)) {
      throw new Error("复核 JSON 缺少 expected_fields");
    }
    return payload;
  }
  return parseTextPayload(text);
}

function expectedPlanName(payload) {
  const direct = normText(payload && payload.plan_name);
  if (direct) return direct;
  const hit = ((payload && payload.expected_fields) || []).find((field) => field.key === "name" || field.name === "计划名称");
  return normText(hit && hit.value);
}

function currentPagePlanName(pageSnapshot) {
  const fields = (pageSnapshot && pageSnapshot.fields) || {};
  const direct = normText(fields.name || fields["计划名称"]);
  if (direct) return direct;
  const text = normText(pageSnapshot && pageSnapshot.pageText);
  const labeled = text.match(/计划名称\s*[：: ]\s*([^\n\r]+)/);
  if (labeled && labeled[1]) return normText(labeled[1]).slice(0, 80);
  const bracketed = text.match(/【[^】]{2,80}】[^\s\n\r]{0,40}/);
  return normText(bracketed && bracketed[0]);
}

function planNameMatches(expected, actual) {
  const exp = compactComparable(expected);
  const got = compactComparable(actual);
  if (!exp || !got) return true;
  return exp === got || exp.includes(got) || got.includes(exp);
}

function renderPlanMismatch(expected, actual, pageSnapshot) {
  const pageLabel = pageSnapshot.title || pageSnapshot.url || "当前页面";
  els.summary.textContent = `复核数据与当前页面不匹配。复核数据：${expected || "未知"}；当前页面：${actual || pageLabel}。请从 /simple 对应行重新复制复核数据后载入。`;
  els.domCount.textContent = "0";
  els.visionCount.textContent = String(visionCalls);
  els.cacheCount.textContent = String(cacheHits);
  els.resultList.innerHTML = `
    <div class="item mismatch">
      <div class="item-head">
        <span>计划名称</span>
        <span class="badge mismatch">数据不匹配</span>
      </div>
      <div class="kv">
        <div class="k">原文</div><div class="v">${escapeHtml(expected || "未读取到")}</div>
        <div class="k">页面</div><div class="v">${escapeHtml(actual || "未读取到")}</div>
        <div class="k">说明</div><div class="v">当前侧边栏仍载入了其他计划的复核数据，已停止对比，避免误判。</div>
      </div>
    </div>`;
}

async function clearLoadedPayload(message, options = {}) {
  reviewPayload = null;
  lastResults = [];
  lastPageSnapshot = {};
  lastPageHash = "";
  visionCalls = 0;
  visionCache.clear();
  if (options.clearInput) {
    els.payloadInput.value = "";
  }
  els.domCount.textContent = "0";
  els.visionCount.textContent = "0";
  if (message) els.summary.textContent = message;
  await chrome.storage.local.remove(["reviewPayload", "reviewPayloadText"]);
}

async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0];
}

function mergePageSnapshots(snapshots) {
  const valid = (snapshots || []).filter(Boolean);
  const merged = { url: "", title: "", fields: {}, pageText: "" };
  for (const snap of valid) {
    if (!merged.url && snap.url) merged.url = snap.url;
    if (!merged.title && snap.title) merged.title = snap.title;
    for (const [key, value] of Object.entries(snap.fields || {})) {
      if (!normText(merged.fields[key]) && normText(value)) {
        merged.fields[key] = value;
      }
    }
    if (snap.pageText) {
      merged.pageText = [merged.pageText, snap.pageText].filter(Boolean).join(" ");
    }
  }
  return merged;
}

async function readAllFrameSnapshots(tab) {
  if (!chrome.scripting || !chrome.scripting.executeScript) return [];
  try {
    const existing = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: () => {
        if (typeof window.__PM_REVIEW_READ_PAGE__ === "function") {
          return window.__PM_REVIEW_READ_PAGE__();
        }
        return null;
      }
    });
    const snapshots = existing.map((item) => item && item.result).filter(Boolean);
    if (snapshots.length) return snapshots;
  } catch (_err) {
    // Continue with explicit injection below.
  }

  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      files: ["content_script.js"]
    });
  } catch (_err) {
    // Some browser/system frames may reject injection. Return whatever can be read afterwards.
  }

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: () => {
        if (typeof window.__PM_REVIEW_READ_PAGE__ === "function") {
          return window.__PM_REVIEW_READ_PAGE__();
        }
        return null;
      }
    });
    return results.map((item) => item && item.result).filter(Boolean);
  } catch (_err) {
    return [];
  }
}

async function readCurrentPage(tab) {
  const frameSnapshots = await readAllFrameSnapshots(tab);
  if (frameSnapshots.length) {
    return mergePageSnapshots(frameSnapshots);
  }
  try {
    return await chrome.tabs.sendMessage(tab.id, { type: "PM_REVIEW_READ_PAGE" });
  } catch (err) {
    const msg = String((err && err.message) || err || "");
    if (!msg.includes("Receiving end does not exist") && !msg.includes("Could not establish connection")) {
      throw err;
    }
  }
  if (!chrome.scripting || !chrome.scripting.executeScript) {
    throw new Error("当前页面未注入复核脚本，请刷新业务页面后重试");
  }
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      files: ["content_script.js"]
    });
  } catch (err) {
    throw new Error(`注入复核脚本失败：${(err && err.message) || err}`);
  }
  const snapshots = await readAllFrameSnapshots(tab);
  if (snapshots.length) return mergePageSnapshots(snapshots);
  return await chrome.tabs.sendMessage(tab.id, { type: "PM_REVIEW_READ_PAGE" });
}

async function loadPayload() {
  const raw = els.payloadInput.value.trim();
  if (!raw) return;
  const payload = parseReviewPayload(raw);
  reviewPayload = payload;
  els.summary.textContent = `已载入：${expectedPlanName(payload) || payload.expected_fields[0]?.value || "未命名计划"}`;
}

async function runReview(force = false) {
  if (!reviewPayload) {
    await loadPayload();
  }
  if (!reviewPayload) return;
  const tab = await activeTab();
  if (!tab || !tab.id) {
    els.pageState.textContent = "无活动页面";
    return;
  }
  els.pageState.textContent = "读取页面中";
  const response = await readCurrentPage(tab);
  const pageSnapshot = response || {};
  const pageHash = JSON.stringify({
    url: pageSnapshot.url,
    title: pageSnapshot.title,
    fields: pageSnapshot.fields,
    text: String(pageSnapshot.pageText || "").slice(0, 3000)
  });
  if (!force && pageHash && pageHash === lastPageHash) {
    cacheHits += 1;
  } else if (pageHash !== lastPageHash) {
    visionCalls = 0;
  }
  lastPageHash = pageHash;
  const pageValues = pageSnapshot.fields || {};
  const pageText = pageSnapshot.pageText || "";
  const expectedName = expectedPlanName(reviewPayload);
  const pageName = currentPagePlanName(pageSnapshot);
  if (expectedName && pageName && !planNameMatches(expectedName, pageName)) {
    lastResults = [];
    lastPageSnapshot = pageSnapshot;
    renderPlanMismatch(expectedName, pageName, pageSnapshot);
    await clearLoadedPayload(els.summary.textContent, { clearInput: false });
    els.pageState.textContent = "数据不匹配";
    return;
  }
  const results = (reviewPayload.expected_fields || []).map((field) => {
    const cmp = compareField(field, pageValues, pageText);
    return {
      name: field.name,
      key: field.key,
      expected: field.value,
      actual: cmp.actual,
      reason: cmp.reason,
      status: cmp.status
    };
  });
  lastResults = results;
  lastPageSnapshot = pageSnapshot;
  render(lastResults, lastPageSnapshot);
  els.pageState.textContent = "已复核";
}

async function captureVisibleDataUrl(tab) {
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
  if (!dataUrl || !dataUrl.startsWith("data:image/")) {
    throw new Error("截图失败");
  }
  return dataUrl;
}

function visionCacheKey(fields, pageSnapshot) {
  const fieldKey = fields.map((x) => `${x.key || ""}:${x.name || ""}:${x.expected || x.value || ""}`).join("|");
  return JSON.stringify({
    url: pageSnapshot.url || "",
    title: pageSnapshot.title || "",
    text: String(pageSnapshot.pageText || "").slice(0, 1200),
    fields: fieldKey
  });
}

function applyVisionFields(results, visionFields) {
  const byName = new Map();
  for (const item of visionFields || []) {
    const name = String(item.name || "").trim();
    if (name) byName.set(name, item);
  }
  return results.map((result) => {
    if (result.status !== "unknown") return result;
    const hit = byName.get(result.name);
    if (!hit) return result;
    const pageValue = normText(hit.page_value || hit.value || "");
    const confidence = Number(hit.confidence || 0);
    if (!pageValue || confidence < 0.65) {
      return {
        ...result,
        actual: pageValue,
        reason: `视觉低置信度(${confidence || 0})，请人工确认`
      };
    }
    const cmp = compareField({ name: result.name, key: result.key, value: result.expected }, { [result.key]: pageValue, [result.name]: pageValue }, "");
    return {
      ...result,
      actual: pageValue,
      status: cmp.status === "unknown" ? "vision" : cmp.status,
      reason: `视觉辅助: ${cmp.reason}; 置信度 ${confidence}`
    };
  });
}

async function runVisionReview() {
  if (!reviewPayload) {
    await loadPayload();
  }
  if (!reviewPayload) return;
  if (!lastResults.length) {
    await runReview(true);
  }
  const unknown = lastResults.filter((x) => x.status === "unknown").slice(0, 8);
  if (!unknown.length) {
    els.summary.textContent = "当前没有待视觉复核字段。";
    return;
  }
  if (visionCalls >= MAX_VISION_CALLS_PER_PAGE) {
    els.summary.textContent = `已达到单页视觉调用上限 ${MAX_VISION_CALLS_PER_PAGE} 次，请人工复核剩余字段。`;
    return;
  }
  const cacheKey = visionCacheKey(unknown, lastPageSnapshot);
  if (visionCache.has(cacheKey)) {
    cacheHits += 1;
    lastResults = applyVisionFields(lastResults, visionCache.get(cacheKey));
    render(lastResults, lastPageSnapshot);
    return;
  }
  const tab = await activeTab();
  if (!tab || !tab.id) throw new Error("无活动页面");
  els.pageState.textContent = "视觉复核中";
  const imageDataUrl = await captureVisibleDataUrl(tab);
  const headers = { "Content-Type": "application/json" };
  const resp = await fetch(visionEndpoint(), {
    method: "POST",
    headers,
    body: JSON.stringify({
      image_data_url: imageDataUrl,
      fields: unknown.map((x) => ({ name: x.name, key: x.key, expected: x.expected })),
      page_context: `${lastPageSnapshot.title || ""} ${lastPageSnapshot.url || ""}`
    })
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.detail || `视觉接口失败 HTTP ${resp.status}`);
  }
  visionCalls += 1;
  const visionFields = data.fields || [];
  visionCache.set(cacheKey, visionFields);
  lastResults = applyVisionFields(lastResults, visionFields);
  render(lastResults, lastPageSnapshot);
  els.pageState.textContent = "已复核";
}

els.textReviewBtn.addEventListener("click", async () => {
  try {
    await runReview(true);
  } catch (err) {
    els.pageState.textContent = "复核失败";
    els.summary.textContent = `复核失败：${err.message || err}`;
  }
});

els.screenshotReviewBtn.addEventListener("click", async () => {
  try {
    await runVisionReview();
  } catch (err) {
    els.pageState.textContent = "视觉复核失败";
    els.summary.textContent = `视觉复核失败：${err.message || err}`;
  }
});

chrome.runtime.onMessage.addListener((msg) => {
  if (!msg || msg.type !== "PM_PAGE_CHANGED") return;
  if (!reviewPayload) return;
  els.pageState.textContent = "页面已变化";
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => runReview(false).catch(() => {}), 1200);
});

els.serviceUrlInput.addEventListener("change", () => {
  saveSettings().catch(() => {});
});
els.serviceUrlInput.addEventListener("blur", () => {
  saveSettings().catch(() => {});
});

loadSettings().catch(() => {});

chrome.storage.local.get(["reviewPayload", "reviewPayloadText"]).then((data) => {
  if (data.reviewPayload || data.reviewPayloadText) {
    chrome.storage.local.remove(["reviewPayload", "reviewPayloadText"]);
    els.payloadInput.value = "";
    els.summary.textContent = "已清空上次复核数据。请从 /simple 当前计划对应行复制复核数据并载入。";
  }
});
