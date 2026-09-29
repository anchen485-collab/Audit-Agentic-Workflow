const uploadForm = getRequiredElement("#uploadForm");
const excelFile = getRequiredElement("#excelFile");
const fileName = getRequiredElement("#fileName");
const submitButton = getRequiredElement("#submitButton");
const statusMessage = getRequiredElement("#statusMessage");
const metricsPanel = getRequiredElement("#metrics");
const resultRows = getRequiredElement("#resultRows");
const reviewRows = getRequiredElement("#reviewRows");
const reviewCount = getRequiredElement("#reviewCount");
const actionFilter = getRequiredElement("#actionFilter");
const authToken = getAuthTokenElement();
const downloadButton = getDownloadButtonElement();

let latestRows = [];
let latestDownloadUrl = "";
let latestBatchId = "";

const actionText = {
    approved: "自动通过",
    rejected: "自动驳回",
    needs_more_evidence: "证据不足",
    needs_human_review: "人工复核",
};

authToken.value = localStorage.getItem("auditAgentAuthToken") || "";

authToken.addEventListener("input", () => {
    localStorage.setItem("auditAgentAuthToken", authToken.value.trim());
});

excelFile.addEventListener("change", () => {
    fileName.textContent = excelFile.files[0]?.name || "仅支持 .xlsx";
});

actionFilter.addEventListener("change", () => {
    renderDecisionRows(latestRows);
});

downloadButton.addEventListener("click", async () => {
    await downloadResultExcel();
});

resultRows.addEventListener("click", async (event) => {
    const retryButton = event.target.closest("[data-retry-case-id]");
    if (!retryButton) {
        return;
    }

    await retryAuditCase(retryButton.dataset.retryCaseId, retryButton);
});

uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!getAuthToken()) {
        setStatus("请先填写访问令牌", true);
        return;
    }

    if (!excelFile.files.length) {
        setStatus("请选择一个 .xlsx 文件", true);
        return;
    }

    const formData = new FormData();
    formData.append("file", excelFile.files[0]);

    submitButton.disabled = true;
    setStatus("审批处理中，请稍候", false);
    clearTables();

    try {
        const response = await fetch("/api/audit/upload", {
            method: "POST",
            headers: buildAuthHeaders(),
            body: formData,
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "审批处理失败");
        }

        latestRows = buildDecisionRows(data);
        latestBatchId = data.batch_id;
        renderMetrics(data.metrics || {});
        renderDecisionRows(latestRows);
        renderReviewRows(data.review_tasks || []);
        updateDownloadButton(data.download_url);
        setStatus(`批次 ${data.batch_id} 已完成`, false);
    } catch (error) {
        setStatus(error.message, true);
        renderEmpty(resultRows, 14, "暂无审批结果");
        renderEmpty(reviewRows, 5, "暂无人工复核任务");
    } finally {
        submitButton.disabled = false;
    }
});

function buildDecisionRows(data) {
    const caseMap = new Map((data.cases || []).map((auditCase) => [auditCase.case_id, auditCase]));

    return (data.decisions || []).map((decision) => {
        const auditCase = caseMap.get(decision.case_id) || {};
        return {
            ...auditCase,
            ...decision,
        };
    });
}

function renderMetrics(metrics) {
    const cards = [
        ["总数", metrics.total_count ?? 0],
        ["自动处理", metrics.auto_handled_count ?? 0],
        ["人工复核", metrics.review_count ?? 0],
        ["自动处理率", formatRate(metrics.auto_handled_rate)],
        ["复核率", formatRate(metrics.review_rate)],
    ];

    metricsPanel.innerHTML = cards.map(([label, value]) => `
        <article class="metric">
            <div class="metric-label">${escapeHtml(label)}</div>
            <div class="metric-value">${escapeHtml(String(value))}</div>
        </article>
    `).join("");
}

function renderDecisionRows(rows) {
    const selectedAction = actionFilter.value;
    const visibleRows = selectedAction
        ? rows.filter((row) => row.action === selectedAction)
        : rows;

    if (!visibleRows.length) {
        renderEmpty(resultRows, 14, "暂无审批结果");
        return;
    }

    resultRows.innerHTML = visibleRows.map((row) => `
        <tr>
            <td>${escapeHtml(row.employee_name || "")}</td>
            <td>${escapeHtml(row.company_name || "")}</td>
            <td>${renderWebsite(row.website_url)}</td>
            <td>${escapeHtml(row.entered_level1 || "")}</td>
            <td>${escapeHtml(row.entered_subcategory || "")}</td>
            <td>${escapeHtml(granularityText(row.entered_subcategory_granularity || ""))}</td>
            <td>${renderLongText(formatCandidatePaths(row.category_candidate_paths || []))}</td>
            <td><span class="badge ${escapeHtml(row.action || "")}">${escapeHtml(actionText[row.action] || row.action || "")}</span></td>
            <td>${escapeHtml(String(row.confidence ?? ""))}</td>
            <td>${escapeHtml(String(row.risk_score ?? ""))}</td>
            <td>${row.needs_review ? "是" : "否"}</td>
            <td class="reason-cell">${renderLongText(row.reason || "")}</td>
            <td>${renderLongText(row.suggestion || "")}</td>
            <td>${renderRetryButton(row.case_id)}</td>
        </tr>
    `).join("");
}

function renderRetryButton(caseId) {
    if (!latestBatchId || !caseId) {
        return "";
    }

    return `<button class="retry-button" type="button" data-retry-case-id="${escapeHtml(caseId)}">重新审批</button>`;
}

async function retryAuditCase(caseId, button) {
    if (!latestBatchId || !caseId) {
        setStatus("请先完成一次审批后再重试", true);
        return;
    }
    if (!getAuthToken()) {
        setStatus("请先填写访问令牌", true);
        return;
    }

    button.disabled = true;
    const idempotencyKey = button.dataset.retryIdempotencyKey || createRetryIdempotencyKey();
    button.dataset.retryIdempotencyKey = idempotencyKey;
    setStatus(`正在重新审批 ${caseId}`, false);
    try {
        const response = await fetch(`/api/audit/batches/${encodeURIComponent(latestBatchId)}/cases/${encodeURIComponent(caseId)}/retry`, {
            method: "POST",
            headers: {
                ...buildAuthHeaders(),
                "Idempotency-Key": idempotencyKey,
            },
        });
        if (!response.ok) {
            const requestError = new Error(await readErrorMessage(response));
            requestError.status = response.status;
            requestError.retrySameKey = response.status >= 500 || response.headers.has("Retry-After");
            throw requestError;
        }

        const data = await response.json();
        delete button.dataset.retryIdempotencyKey;
        latestRows = latestRows.map((row) => row.case_id === caseId ? { ...row, ...data.decision } : row);
        renderMetrics(data.metrics || {});
        renderDecisionRows(latestRows);
        renderReviewRows(data.review_tasks || []);
        const resultText = data.idempotent_replay ? "已返回此前完成的重试结果" : "已重新审批";
        setStatus(`审批单 ${caseId} ${resultText}`, false);
    } catch (error) {
        if (error.status && !error.retrySameKey) {
            delete button.dataset.retryIdempotencyKey;
        }
        setStatus(error.message, true);
    } finally {
        button.disabled = false;
    }
}

function createRetryIdempotencyKey() {
    if (window.crypto?.randomUUID) {
        return `case-retry:${window.crypto.randomUUID()}`;
    }

    return `case-retry:${Date.now()}:${Math.random().toString(16).slice(2)}`;
}

function renderReviewRows(tasks) {
    reviewCount.textContent = `${tasks.length} 条`;

    if (!tasks.length) {
        renderEmpty(reviewRows, 5, "暂无人工复核任务");
        return;
    }

    reviewRows.innerHTML = tasks.map((task) => `
        <tr>
            <td>${escapeHtml(task.task_id || "")}</td>
            <td>${escapeHtml(task.case_id || "")}</td>
            <td>${escapeHtml(task.priority || "")}</td>
            <td>${escapeHtml(task.reason || "")}</td>
            <td>${escapeHtml(task.status || "")}</td>
        </tr>
    `).join("");
}

function updateDownloadButton(downloadUrl) {
    latestDownloadUrl = downloadUrl || "";

    if (!downloadUrl) {
        downloadButton.classList.add("is-hidden");
        return;
    }

    downloadButton.classList.remove("is-hidden");
}

async function downloadResultExcel() {
    if (!latestDownloadUrl) {
        return;
    }

    if (!getAuthToken()) {
        setStatus("请先填写访问令牌", true);
        return;
    }

    downloadButton.disabled = true;
    setStatus("正在下载结果 Excel", false);

    try {
        const response = await fetch(latestDownloadUrl, {
            method: "GET",
            headers: buildAuthHeaders(),
        });

        if (!response.ok) {
            const errorText = await readErrorMessage(response);
            throw new Error(errorText || "下载失败");
        }

        const blob = await response.blob();
        const filename = parseDownloadFilename(response) || "audit_result.xlsx";
        triggerBlobDownload(blob, filename);
        setStatus("结果 Excel 已开始下载", false);
    } catch (error) {
        setStatus(error.message, true);
    } finally {
        downloadButton.disabled = false;
    }
}

function buildAuthHeaders() {
    const token = getAuthToken();
    if (!token) {
        return {};
    }

    return {
        Authorization: `Bearer ${token}`,
    };
}

function getAuthToken() {
    return authToken.value.trim();
}

async function readErrorMessage(response) {
    try {
        const data = await response.json();
        return data.detail || "请求失败";
    } catch {
        return "请求失败";
    }
}

function parseDownloadFilename(response) {
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/i);

    return match ? match[1] : "";
}

function triggerBlobDownload(blob, filename) {
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
}

function clearTables() {
    metricsPanel.innerHTML = "";
    latestRows = [];
    renderEmpty(resultRows, 14, "审批处理中");
    renderEmpty(reviewRows, 5, "审批处理中");
    reviewCount.textContent = "0 条";
    latestDownloadUrl = "";
    latestBatchId = "";
    downloadButton.classList.add("is-hidden");
}

function renderEmpty(target, colspan, text) {
    target.innerHTML = `<tr><td colspan="${colspan}" class="empty-cell">${escapeHtml(text)}</td></tr>`;
}

function renderWebsite(value) {
    if (!value) {
        return "";
    }

    const safeValue = escapeHtml(value);
    return `<a href="${safeValue}" target="_blank" rel="noreferrer">${safeValue}</a>`;
}

function renderLongText(value) {
    if (!value) {
        return "";
    }

    const safeValue = escapeHtml(value);
    return `<div class="cell-scroll" title="${safeValue}">${safeValue}</div>`;
}

function formatRate(value) {
    if (value === undefined || value === null || Number.isNaN(Number(value))) {
        return "0%";
    }

    return `${Math.round(Number(value) * 100)}%`;
}

function granularityText(value) {
    const mapping = {
        level2: "二级",
        level3: "三级",
        mixed: "混合",
        ambiguous: "歧义",
        unknown: "未知",
    };

    return mapping[value] || value;
}

function formatCandidatePaths(paths) {
    if (!Array.isArray(paths) || !paths.length) {
        return "";
    }

    return paths.join("；");
}

function setStatus(message, isError) {
    statusMessage.textContent = message;
    statusMessage.classList.toggle("error", isError);
}

function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function getRequiredElement(selector) {
    const element = document.querySelector(selector);
    if (!element) {
        const message = `页面缺少必要元素：${selector}，请强制刷新页面后重试。`;
        console.error(message);
        throw new Error(message);
    }

    return element;
}

function getAuthTokenElement() {
    const existingToken = document.querySelector("#authToken");
    if (existingToken) {
        return existingToken;
    }

    const topbar = document.querySelector(".topbar");
    const tokenLabel = document.createElement("label");
    tokenLabel.className = "token-field";
    tokenLabel.innerHTML = '<span>访问令牌</span><input id="authToken" type="password" autocomplete="off">';
    topbar?.appendChild(tokenLabel);

    return getRequiredElement("#authToken");
}

function getDownloadButtonElement() {
    const existingButton = document.querySelector("#downloadButton");
    if (existingButton) {
        return existingButton;
    }

    const oldDownloadLink = document.querySelector("#downloadLink");
    const button = document.createElement("button");
    button.id = "downloadButton";
    button.className = "download-link is-hidden";
    button.type = "button";
    button.textContent = "下载 Excel";

    if (oldDownloadLink?.parentElement) {
        oldDownloadLink.replaceWith(button);
    } else {
        document.querySelector(".table-actions")?.appendChild(button);
    }

    return getRequiredElement("#downloadButton");
}
