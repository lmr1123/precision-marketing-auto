function isVisible(el) {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
}

function cleanText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function normText(value) {
  return cleanText(value).replace(/[：:*＊]/g, "").trim();
}

function readValueFromContainer(container) {
  if (!container) return "";
  const values = [];
  const controls = Array.from(container.querySelectorAll("input, textarea, [contenteditable='true']")).filter(isVisible);
  for (const el of controls) {
    const value = el.tagName === "INPUT" || el.tagName === "TEXTAREA" ? el.value : el.innerText;
    if (cleanText(value)) values.push(value.trim());
  }
  const tagSelectors = [
    ".el-tag",
    ".ant-tag",
    ".el-select__tags-text",
    ".el-select__selected-item",
    ".ant-select-selection-item",
    ".ant-select-selection-item-content",
    ".el-cascader__tags .el-tag",
    "[class*='selected']"
  ];
  for (const selector of tagSelectors) {
    for (const el of Array.from(container.querySelectorAll(selector)).filter(isVisible)) {
      const text = cleanText(el.textContent);
      if (text && !values.includes(text)) values.push(text);
    }
  }
  if (values.length) return values.join("、");
  return cleanText(container.textContent);
}

function cleanFieldValue(value, aliases) {
  let out = cleanText(value);
  for (const alias of aliases) {
    out = out.replace(alias, "");
  }
  return out.replace(/[：:*＊]/g, " ").trim();
}

function containerForLabel(labelEl) {
  const selectors = [".item", ".el-form-item", ".ant-form-item", ".el-row", ".ant-row", "tr", "li"];
  for (const selector of selectors) {
    const hit = labelEl.closest(selector);
    if (hit && isVisible(hit)) return hit;
  }
  return labelEl.parentElement;
}

function readInputValueFromContainer(container, aliases) {
  if (!container) return "";
  const controls = Array.from(container.querySelectorAll("input, textarea, [contenteditable='true']")).filter(isVisible);
  for (const el of controls) {
    const value = el.tagName === "INPUT" || el.tagName === "TEXTAREA" ? el.value : el.innerText;
    const cleaned = cleanFieldValue(value, aliases);
    if (cleaned) return cleaned;
  }
  return "";
}

function readPlanName() {
  const aliases = ["计划名称", "营销计划"];
  const labels = Array.from(document.querySelectorAll("label, .label, .el-form-item__label, .ant-form-item-label"))
    .filter(isVisible);
  for (const labelEl of labels) {
    const labelText = cleanText(labelEl.textContent);
    if (!aliases.some((alias) => normText(labelText).includes(alias))) continue;
    const container = containerForLabel(labelEl);
    const value = readInputValueFromContainer(container, aliases);
    if (value) return value;
    const nodes = Array.from((container || labelEl.parentElement || document.body).querySelectorAll(".value, .text, .content, .ant-form-text, .el-form-item__content span, .ant-form-item-control span"))
      .filter(isVisible);
    for (const node of nodes) {
      const valueFromNode = cleanFieldValue(node.textContent, aliases);
      if (valueFromNode && valueFromNode.length <= 100 && valueFromNode !== labelText) return valueFromNode;
    }
  }
  const bodyText = document.body ? document.body.innerText || "" : "";
  const labeled = bodyText.match(/计划名称\s*[：:]\s*([^\n\r]{2,100})/);
  return labeled ? cleanText(labeled[1]) : "";
}

function readTableValueByHeader(aliases) {
  const tables = Array.from(document.querySelectorAll("table, .el-table, .ant-table")).filter(isVisible);
  for (const table of tables) {
    const rows = Array.from(table.querySelectorAll("tr")).filter(isVisible);
    for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
      const cells = Array.from(rows[rowIndex].querySelectorAll("th, td, .cell")).filter(isVisible);
      const headerIndex = cells.findIndex((cell) => {
        const text = cleanText(cell.textContent);
        return aliases.some((alias) => text === alias || text.includes(alias));
      });
      if (headerIndex < 0) continue;
      for (let nextIndex = rowIndex + 1; nextIndex < rows.length; nextIndex++) {
        const nextCells = Array.from(rows[nextIndex].querySelectorAll("th, td, .cell")).filter(isVisible);
        const value = cleanFieldValue(nextCells[headerIndex]?.textContent || "", aliases);
        if (value) return value;
      }
    }
  }
  return "";
}

function readParameterDetailValue(parameterAliases) {
  const headerScopes = Array.from(document.querySelectorAll("table, .el-table, .ant-table, .el-row, .ant-row, section, div"))
    .filter(isVisible)
    .filter((scope) => {
      const text = cleanText(scope.textContent);
      return text.includes("参数名称") && text.includes("参数详情") && text.length < 3000;
    });

  for (const scope of headerScopes) {
    const rows = Array.from(scope.querySelectorAll("tr, .el-table__row, .ant-table-row, .el-row, .ant-row"))
      .filter(isVisible);
    for (const row of rows) {
      const rowText = cleanText(row.textContent);
      if (!parameterAliases.some((alias) => rowText.includes(alias))) continue;
      const value = readInputValueFromContainer(row, parameterAliases.concat(["参数名称", "参数详情"]));
      if (value) return value;
    }
  }

  const labels = Array.from(document.querySelectorAll("input, textarea, [contenteditable='true'], span, div"))
    .filter(isVisible);
  for (let i = 0; i < labels.length; i++) {
    const labelText = cleanText(labels[i].tagName === "INPUT" || labels[i].tagName === "TEXTAREA" ? labels[i].value : labels[i].textContent);
    if (!parameterAliases.some((alias) => labelText === alias || labelText.includes(alias))) continue;
    for (let j = i + 1; j < Math.min(labels.length, i + 8); j++) {
      const node = labels[j];
      if (node.tagName !== "INPUT" && node.tagName !== "TEXTAREA" && node.getAttribute("contenteditable") !== "true") continue;
      const value = cleanFieldValue(node.tagName === "INPUT" || node.tagName === "TEXTAREA" ? node.value : node.innerText, parameterAliases);
      if (value && !parameterAliases.includes(value)) return value;
    }
  }
  return "";
}

function readChannels() {
  return (
    readTableValueByHeader(["通知渠道", "发送渠道", "触达渠道"]) ||
    readByAliases(["发送渠道", "触达渠道", "通知渠道"])
  );
}

function readEndTimeInChannelSection() {
  const datePattern = /\d{4}[-/年]\d{1,2}[-/月]\d{1,2}(?:日)?(?:\s+\d{1,2}[:：\s]\d{1,2}(?:[:：\s]\d{1,2})?)?/;
  const channelPattern = /会员通.*(朋友圈|客户消息|社群)|客户朋友圈|客户消息|发客户朋友圈|发送社群|社群群发|社群/;
  const endTimeLabelPattern = /^[*＊\s]*结束时间[:：*＊\s]*$/;
  const headings = Array.from(document.querySelectorAll("h1, h2, h3, h4, h5, .title, .section-title, .card-title, .ant-card-head-title, .el-card__header, div, span"))
    .filter(isVisible);
  const channelHeading = headings.find((el) => {
    const text = cleanText(el.textContent);
    return text.length <= 100 && channelPattern.test(text);
  });
  const section = channelHeading
    ? (channelHeading.closest(".section, .card, .el-card, .ant-card, .form-section, .content, .ant-form, .el-form") || channelHeading.parentElement)
    : null;
  if (section) {
    const labels = Array.from(section.querySelectorAll("label, .label, .el-form-item__label, .ant-form-item-label, span, div"))
      .filter(isVisible);
    for (const labelEl of labels) {
      const labelText = cleanText(labelEl.textContent);
      if (!endTimeLabelPattern.test(labelText)) continue;
      const container = containerForLabel(labelEl);
      const value = readInputValueFromContainer(container, ["结束时间"]);
      if (value) return value;
      const raw = cleanFieldValue(readValueFromContainer(container), ["结束时间"]);
      if (raw) return raw;
    }
  }

  const visibleNodes = Array.from(document.querySelectorAll("label, .label, .el-form-item__label, .ant-form-item-label, span, div, input"))
    .filter(isVisible);
  const channelIndex = visibleNodes.findIndex((el) => {
    const text = cleanText(el.tagName === "INPUT" ? el.value : el.textContent);
    return text.length <= 100 && channelPattern.test(text);
  });
  if (channelIndex < 0) return "";
  for (let i = channelIndex; i < Math.min(visibleNodes.length, channelIndex + 80); i++) {
    const labelEl = visibleNodes[i];
    const labelText = cleanText(labelEl.tagName === "INPUT" ? labelEl.value : labelEl.textContent);
    if (!endTimeLabelPattern.test(labelText)) continue;
    const container = containerForLabel(labelEl);
    const value = readInputValueFromContainer(container, ["结束时间"]);
    if (value && datePattern.test(value)) return value;
    const raw = cleanFieldValue(readValueFromContainer(container), ["结束时间"]);
    if (raw && datePattern.test(raw)) return raw;
    for (let j = i + 1; j < Math.min(visibleNodes.length, i + 8); j++) {
      const node = visibleNodes[j];
      const text = cleanText(node.tagName === "INPUT" ? node.value : node.textContent);
      const match = text.match(datePattern);
      if (match) return match[0];
    }
  }
  return "";
}

function readByAliases(aliases) {
  const labels = Array.from(document.querySelectorAll("label, .label, .el-form-item__label, .ant-form-item-label, th, dt, span, div"))
    .filter(isVisible);
  for (const labelEl of labels) {
    const labelText = cleanText(labelEl.textContent);
    if (!labelText || labelText.length > 32) continue;
    if (!aliases.some((alias) => labelText.includes(alias))) continue;
    const container = containerForLabel(labelEl);
    if (!container) continue;
    let value = readValueFromContainer(container);
    for (const alias of aliases) {
      value = value.replace(alias, "");
    }
    value = value.replace(/[：:*＊]/g, " ").trim();
    if (value) return value;
  }
  return "";
}

function countVisibleImages() {
  const imageNodes = Array.from(document.querySelectorAll(
    ".el-upload-list img, .ant-upload-list img, [class*='upload'] img, [class*='image'] img, [class*='picture'] img"
  )).filter(isVisible);
  const names = new Set();
  const filePattern = /(?:图片\)?\s*)?([^\s，,；;]*\.(?:png|jpe?g|webp|gif|bmp))/i;
  const fileNodes = Array.from(document.querySelectorAll(
    ".el-upload-list__item-name, .ant-upload-list-item-name, [class*='upload-list'] [title], [class*='upload'] span, [class*='file'] span, [class*='image'] span, a, span, div"
  )).filter(isVisible);
  for (const node of fileNodes) {
    const text = cleanText(node.getAttribute("title") || node.textContent);
    const match = text.match(filePattern);
    if (match && match[1]) names.add(match[1]);
  }
  const count = Math.max(imageNodes.length, names.size);
  return count ? String(count) : "";
}

function readPage() {
  const planName = readPlanName();
  const channels = readChannels();
  const step3EndTime = readByAliases(["员工任务结束时间"]) || readEndTimeInChannelSection();
  const activityIntro = readParameterDetailValue(["活动介绍"]) || readByAliases(["活动介绍", "参数详情"]);
  const fields = {
    name: planName,
    "计划名称": planName,
    channels,
    "发送渠道": channels,
    theme: readByAliases(["营销主题", "主题"]),
    "营销主题": readByAliases(["营销主题", "主题"]),
    region: readByAliases(["计划区域", "区域"]),
    "计划区域": readByAliases(["计划区域", "区域"]),
    start_time: readByAliases(["计划开始时间", "开始时间", "计划时间"]),
    "计划开始时间": readByAliases(["计划开始时间", "开始时间", "计划时间"]),
    end_time: readByAliases(["计划结束时间", "结束时间", "计划时间"]),
    "计划结束时间": readByAliases(["计划结束时间", "结束时间", "计划时间"]),
    send_time: readByAliases(["发送时间", "推送时间"]),
    "发送时间": readByAliases(["发送时间", "推送时间"]),
    main_operating_area: readByAliases(["主消费营运区", "主消费运营区", "主消费门店"]),
    "主消费营运区": readByAliases(["主消费营运区", "主消费运营区", "主消费门店"]),
    executor_employees: readByAliases(["执行员工"]),
    "执行员工": readByAliases(["执行员工"]),
    product_codes: readByAliases(["目标商品编码", "购买目标商品编码", "商品编码"]),
    "目标商品编码": readByAliases(["目标商品编码", "购买目标商品编码", "商品编码"]),
    coupon_ids: readByAliases(["已领或已使用券规则ID", "券规则ID", "券规则"]),
    "已领或已使用券规则ID": readByAliases(["已领或已使用券规则ID", "券规则ID", "券规则"]),
    step3_end_time: step3EndTime,
    "员工任务结束时间": step3EndTime,
    sms_content: readByAliases(["短信内容"]),
    "短信内容": readByAliases(["短信内容"]),
    send_content: readByAliases(["发送内容", "推送内容", "朋友圈内容"]),
    "发送内容": readByAliases(["发送内容", "推送内容", "朋友圈内容"]),
    activity_intro: activityIntro,
    "活动介绍": activityIntro,
    group_send_name: readByAliases(["下发群名", "群名"]),
    "社群下发群名": readByAliases(["下发群名", "群名"]),
    distribution_mode: readByAliases(["分配方式"]),
    "分配方式": readByAliases(["分配方式"]),
    image_count: countVisibleImages(),
    "图片数量": countVisibleImages()
  };
  return {
    url: location.href,
    title: document.title,
    fields,
    pageText: cleanText(document.body ? document.body.innerText : "")
  };
}

window.__PM_REVIEW_READ_PAGE__ = readPage;

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.type !== "PM_REVIEW_READ_PAGE") return false;
  sendResponse(readPage());
  return false;
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.type !== "PM_REVIEW_CAPTURE_VISIBLE") return false;
  sendResponse({
    url: location.href,
    title: document.title,
    pageText: cleanText(document.body ? document.body.innerText : "")
  });
  return false;
});

let timer = null;
let extensionContextAlive = true;

function stopPageObserver() {
  extensionContextAlive = false;
  clearTimeout(timer);
  try {
    observer.disconnect();
  } catch (_err) {
    // The page may unload while the extension is reloading.
  }
}

function notifyPageChanged() {
  if (!extensionContextAlive) return;
  try {
    if (!chrome || !chrome.runtime || !chrome.runtime.id) {
      stopPageObserver();
      return;
    }
    chrome.runtime
      .sendMessage({ type: "PM_PAGE_CHANGED", url: location.href })
      .catch(() => stopPageObserver());
  } catch (_err) {
    stopPageObserver();
  }
}

const observer = new MutationObserver(() => {
  if (!extensionContextAlive) return;
  clearTimeout(timer);
  timer = setTimeout(notifyPageChanged, 900);
});

if (document.documentElement) {
  observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true });
}
