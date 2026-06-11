const DEFAULT_POLICY_KEY = "review-policy";
const DEFAULT_REVIEW_DESTINATION_KEY = "review-album";
const DEFAULT_DESCRIPTION_DESTINATION_KEY = "asset-description";
const DEFAULT_DESCRIPTION_RESOURCE_ID = "asset-description";
const DEFAULT_REVIEW_THRESHOLD = 0.5;
const LIVE_RELOAD_ENDPOINT = "/api/dev/live-reload";
const LIVE_RELOAD_DEFAULT_INTERVAL_MS = 1000;
const JOB_HISTORY_STORAGE_KEY = "smart-ranker-job-history";
const RUNTIME_RESET_TOKEN_STORAGE_KEY = "smart-ranker-runtime-reset-token";
const MAX_JOB_HISTORY = 12;
const SCORE_REVIEW_PAGE_SIZE = 100;
const DEFAULT_SCORE_REVIEW_SORT_ORDER = "asc";

const normalizeRoute = (path) => {
  const normalized = String(path ?? "/").replace(/\/+$/, "") || "/";
  if (normalized === "/settings") {
    return "settings";
  }
  if (normalized === "/score-review") {
    return "score-review";
  }
  return "home";
};

const normalizeStoredJobRun = (jobRun) => {
  if (!jobRun || !jobRun.jobRunId || !jobRun.jobType) {
    return null;
  }

  return {
    jobRunId: String(jobRun.jobRunId),
    jobType: String(jobRun.jobType),
    status: String(jobRun.status ?? "unknown"),
    submittedAt: String(jobRun.submittedAt ?? ""),
    payload: typeof jobRun.payload === "object" && jobRun.payload !== null ? jobRun.payload : {},
    result: jobRun.result ?? null,
  };
};

const loadJobHistory = () => {
  if (typeof window === "undefined" || !("localStorage" in window)) {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(JOB_HISTORY_STORAGE_KEY);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed.map((item) => normalizeStoredJobRun(item)).filter(Boolean);
  } catch {
    return [];
  }
};

const loadRuntimeResetToken = () => {
  if (typeof window === "undefined" || !("localStorage" in window)) {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(RUNTIME_RESET_TOKEN_STORAGE_KEY);
    return raw ? String(raw) : null;
  } catch {
    return null;
  }
};

const CATEGORY_TYPE_OPTIONS = [
  { value: "core", label: "core" },
  { value: "person", label: "person" },
  { value: "fallback", label: "fallback" },
];

const MEDIA_SCOPE_OPTIONS = [
  { value: "all", label: "all" },
  { value: "image", label: "image" },
  { value: "video", label: "video" },
];

const ROUTING_MODE_OPTIONS = [
  { value: "person_group", label: "person group" },
  { value: "mechanical", label: "mechanical" },
  { value: "smart_search", label: "smart search" },
  { value: "fallback", label: "fallback" },
];

const MECHANICAL_SOURCE_OPTIONS = [
  { value: "ocr_text", label: "ocr_text" },
  { value: "file_name", label: "file_name" },
  { value: "original_path", label: "original_path" },
  { value: "tag_names", label: "tag_names" },
];

const SCHEDULE_MODE_OPTIONS = [
  { value: "manual", label: "manual" },
  { value: "cron", label: "cron" },
];

const state = {
  settings: {
    personGroups: [],
    categories: [],
    routingRules: [],
    policies: [],
    destinations: [],
    schedules: [],
    models: [],
    ledger: {
      feedbackEvents: [],
      inferenceTraces: [],
      actionExecutionLogs: [],
      favoriteSignals: [],
      trashSignals: [],
      scoreRuns: [],
      scoreResults: [],
      applyExclusionAssets: [],
    },
  },
  ui: {
    currentRoute: normalizeRoute(window.location.pathname),
    jobHistory: loadJobHistory(),
    runtimeResetToken: loadRuntimeResetToken(),
    selectedPersonGroupKey: null,
    personSearchQuery: "",
    personSearchResults: [],
    personReplaceTarget: null,
    scoreReview: {
      items: [],
      page: 1,
      pageSize: SCORE_REVIEW_PAGE_SIZE,
      sortOrder: DEFAULT_SCORE_REVIEW_SORT_ORDER,
      totalItems: 0,
      totalPages: 0,
      scoreRunId: null,
      scoreRun: null,
    },
  },
};

const liveReloadState = {
  currentToken: null,
  intervalMs: LIVE_RELOAD_DEFAULT_INTERVAL_MS,
  timeoutId: null,
};

const renderList = (elementId, items, formatter) => {
  const element = document.getElementById(elementId);
  element.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("li");
    empty.textContent = "empty";
    element.appendChild(empty);
    return;
  }

  for (const item of items) {
    const listItem = document.createElement("li");
    listItem.textContent = formatter(item);
    element.appendChild(listItem);
  }
};

const fetchJson = async (url, options = undefined) => {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail ?? payload.error ?? response.statusText);
  }
  return payload;
};

const fetchLiveReloadStatus = async () => {
  const response = await fetch(LIVE_RELOAD_ENDPOINT, {
    cache: "no-store",
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`live reload status failed: ${response.status}`);
  }

  return response.json();
};

const scheduleLiveReloadPoll = (delayMs = liveReloadState.intervalMs) => {
  if (liveReloadState.timeoutId !== null) {
    window.clearTimeout(liveReloadState.timeoutId);
  }

  liveReloadState.timeoutId = window.setTimeout(() => {
    void pollLiveReload();
  }, delayMs);
};

const pollLiveReload = async () => {
  try {
    const payload = await fetchLiveReloadStatus();
    liveReloadState.intervalMs = Number(payload.intervalMs) > 0
      ? Number(payload.intervalMs)
      : LIVE_RELOAD_DEFAULT_INTERVAL_MS;

    if (!payload.enabled) {
      liveReloadState.currentToken = null;
      return;
    }

    const nextToken = String(payload.token ?? "");
    if (liveReloadState.currentToken && nextToken && liveReloadState.currentToken !== nextToken) {
      window.location.reload();
      return;
    }

    liveReloadState.currentToken = nextToken;
  } catch {
    // Ignore transient failures while Uvicorn is restarting in reload mode.
  }

  scheduleLiveReloadPoll();
};

const startLiveReload = () => {
  scheduleLiveReloadPoll(0);
};

const persistJobHistory = () => {
  if (typeof window === "undefined" || !("localStorage" in window)) {
    return;
  }

  try {
    window.localStorage.setItem(JOB_HISTORY_STORAGE_KEY, JSON.stringify(state.ui.jobHistory));
  } catch {
    // Ignore storage errors so the console still works in private browsing or quota pressure.
  }
};

const persistRuntimeResetToken = () => {
  if (typeof window === "undefined" || !("localStorage" in window)) {
    return;
  }

  try {
    if (state.ui.runtimeResetToken) {
      window.localStorage.setItem(RUNTIME_RESET_TOKEN_STORAGE_KEY, state.ui.runtimeResetToken);
      return;
    }
    window.localStorage.removeItem(RUNTIME_RESET_TOKEN_STORAGE_KEY);
  } catch {
    // Ignore storage errors so the console still works in private browsing or quota pressure.
  }
};

const syncJobHistoryWithRuntimeResetToken = (runtimeResetToken) => {
  if (!runtimeResetToken) {
    return;
  }

  const normalizedToken = String(runtimeResetToken);
  if (state.ui.runtimeResetToken && state.ui.runtimeResetToken === normalizedToken) {
    return;
  }

  state.ui.runtimeResetToken = normalizedToken;
  state.ui.jobHistory = [];
  persistJobHistory();
  persistRuntimeResetToken();
};

const setStatus = (elementId, message, isError = false) => {
  const element = document.getElementById(elementId);
  if (!element) {
    return;
  }
  element.textContent = message;
  element.classList.toggle("is-error", isError);
};

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");

const joinCommaSeparated = (items) => (items ?? []).join(", ");

const splitCommaSeparated = (value) => String(value ?? "")
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean);

const createTempId = (prefix) => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 100000)}`;
};

const rememberJobRun = (jobRun) => {
  const normalized = normalizeStoredJobRun(jobRun);
  if (normalized === null) {
    return;
  }

  state.ui.jobHistory = [
    normalized,
    ...state.ui.jobHistory.filter((item) => item.jobRunId !== normalized.jobRunId),
  ].slice(0, MAX_JOB_HISTORY);
  persistJobHistory();
};

const compareIsoTimestamp = (left, right) => String(right ?? "").localeCompare(String(left ?? ""));

const getLatestItem = (items, field) => [...items]
  .filter((item) => item && item[field])
  .sort((left, right) => compareIsoTimestamp(left[field], right[field]))[0] ?? null;

const getRecentJobRun = (jobType) => state.ui.jobHistory.find((jobRun) => jobRun.jobType === jobType) ?? null;

const getLatestModelSnapshot = () => getLatestItem(state.settings.models, "trainedAt");

const getLatestScoreRun = () => getLatestItem(state.settings.ledger.scoreRuns, "completed_at")
  ?? getLatestItem(state.settings.ledger.scoreRuns, "started_at");

const getLatestScoreResult = () => state.settings.ledger.scoreResults?.[0] ?? null;

const getLatestTrace = () => getLatestItem(state.settings.ledger.inferenceTraces, "occurred_at");

const getLatestActionLog = () => getLatestItem(state.settings.ledger.actionExecutionLogs, "executed_at");

const getFileName = (value) => {
  const parts = String(value ?? "").split("/").filter(Boolean);
  return parts.at(-1) ?? "";
};

const formatDateTime = (value) => {
  if (!value) {
    return "n/a";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return new Intl.DateTimeFormat("ja-JP", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
};

const formatCount = (value) => new Intl.NumberFormat("ja-JP").format(Number(value) || 0);

const formatScore = (value) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "n/a";
  }

  const scaled = 100;
  const ceiled = Math.ceil((numeric * scaled) - 1e-9) / scaled;
  return ceiled.toFixed(2);
};

const normalizeScoreReviewSortOrder = (value) => (String(value ?? "").toLowerCase() === "desc"
  ? "desc"
  : DEFAULT_SCORE_REVIEW_SORT_ORDER);

const formatScoreReviewSortLabel = (sortOrder) => (normalizeScoreReviewSortOrder(sortOrder) === "desc"
  ? "score high -> low"
  : "score low -> high");

const resolveScoreReviewTargetPage = (value, totalPages = state.ui.scoreReview.totalPages) => {
  const normalized = String(value ?? "").trim();
  const maxPage = Math.max(1, Number(totalPages) || 1);
  if (!/^\d+$/.test(normalized)) {
    return null;
  }
  return Math.min(maxPage, Math.max(1, Number(normalized)));
};

const buildScoreReviewRequestUrl = (page = state.ui.scoreReview.page) => {
  const params = new URLSearchParams({
    page: String(Math.max(1, Number(page) || 1)),
    pageSize: String(state.ui.scoreReview.pageSize || SCORE_REVIEW_PAGE_SIZE),
    sortOrder: normalizeScoreReviewSortOrder(state.ui.scoreReview.sortOrder),
  });
  if (state.ui.scoreReview.scoreRunId) {
    params.set("scoreRunId", state.ui.scoreReview.scoreRunId);
  }
  return `/api/score-review?${params.toString()}`;
};

const applyScoreReviewPayload = (payload) => {
  state.ui.scoreReview = {
    items: Array.isArray(payload?.items) ? payload.items : [],
    page: Math.max(1, Number(payload?.page) || 1),
    pageSize: Math.max(1, Number(payload?.pageSize) || SCORE_REVIEW_PAGE_SIZE),
    sortOrder: normalizeScoreReviewSortOrder(payload?.sortOrder),
    totalItems: Math.max(0, Number(payload?.totalItems) || 0),
    totalPages: Math.max(0, Number(payload?.totalPages) || 0),
    scoreRunId: payload?.scoreRunId ? String(payload.scoreRunId) : null,
    scoreRun: payload?.scoreRun ?? null,
  };
};

const renderScoreReviewStatus = () => {
  setStatus(
    "score-review-status",
    state.ui.scoreReview.totalItems
      ? `showing ${formatScoreReviewRange()}`
      : "score result not available yet",
  );
};

const reloadScoreReviewPage = async (page) => {
  setStatus("score-review-status", "loading score review...");
  await loadScoreReviewPage(page);
  renderAll();
  renderScoreReviewStatus();
};

const formatScoreReviewRange = () => {
  const { items, page, pageSize, totalItems } = state.ui.scoreReview;
  if (!items.length || !totalItems) {
    return "0 / 0";
  }
  const start = (page - 1) * pageSize + 1;
  const end = start + items.length - 1;
  return `${formatCount(start)}-${formatCount(end)} / ${formatCount(totalItems)}`;
};

const loadScoreReviewPage = async (page = state.ui.scoreReview.page) => {
  const payload = await fetchJson(buildScoreReviewRequestUrl(page));
  applyScoreReviewPayload(payload);
  return payload;
};

const formatJobResultSummary = (jobRun) => {
  if (!jobRun) {
    return "not run yet";
  }

  const result = jobRun.result ?? {};
  if (jobRun.status === "failed") {
    return String(result.error ?? result.errorType ?? "job failed");
  }

  if (jobRun.jobType === "learn") {
    return `signals ${formatCount(result.favoriteSignalCount)} fav / ${formatCount(result.trashSignalCount)} trash / models ${formatCount(result.modelCount)}`;
  }

  if (jobRun.jobType === "score") {
    return `scored ${formatCount(result.scoredAssetCount)} / threshold ${formatScore(result.threshold)}`;
  }

  if (jobRun.jobType === "apply") {
    return `applied ${formatCount(result.appliedCount)}${result.dryRun ? " / dry run" : ""}`;
  }

  return `${jobRun.jobType} completed`;
};

const renderJobOutput = (jobRun = state.ui.jobHistory[0] ?? null) => {
  const output = document.getElementById("job-output");
  if (!output) {
    return;
  }

  if (jobRun === null) {
    output.textContent = "Run learn / score / apply to inspect the accepted payload and final result.";
    return;
  }

  output.textContent = JSON.stringify(jobRun, null, 2);
};

const buildStageCards = () => {
  const learnRun = getRecentJobRun("learn");
  const scoreRun = getRecentJobRun("score");
  const applyRun = getRecentJobRun("apply");
  const latestModel = getLatestModelSnapshot();
  const latestScoreRun = getLatestScoreRun();
  const latestScoreResult = getLatestScoreResult();
  const latestAction = getLatestActionLog();

  const stages = [
    {
      title: "Learn",
      jobRun: learnRun,
      fallbackActive: latestModel !== null,
      note: learnRun
        ? "favorite / trash signal の同期と model 学習の結果です。"
        : latestModel
          ? "保存済み snapshot から直近の learn 結果を読み出しています。"
          : "learn 実行後に signal 数と snapshot がここへ出ます。",
      facts: learnRun
        ? [
          { label: "favorite", value: formatCount(learnRun.result?.favoriteSignalCount) },
          { label: "trash", value: formatCount(learnRun.result?.trashSignalCount) },
          { label: "models", value: formatCount(learnRun.result?.modelCount) },
          { label: "snapshot", value: getFileName(learnRun.result?.snapshotPath) || "n/a" },
        ]
        : latestModel
          ? [
            { label: "run id", value: String(latestModel.runId ?? "n/a") },
            { label: "trained at", value: formatDateTime(latestModel.trainedAt) },
            { label: "models", value: String((latestModel.models ?? []).map((model) => model.model_key ?? "unknown").join(", ") || "n/a") },
          ]
          : [
            { label: "status", value: "idle" },
            { label: "waiting", value: "learn snapshot" },
          ],
    },
    {
      title: "Score",
      jobRun: scoreRun,
      fallbackActive: latestScoreRun !== null,
      note: scoreRun
        ? "全アセット採点と score review の結果です。"
        : latestScoreRun
          ? "保存済み score run から直近の review 結果を可視化しています。"
          : "score 実行後に score review がここへ反映されます。",
      facts: scoreRun
        ? [
          { label: "scored", value: formatCount(scoreRun.result?.scoredAssetCount) },
          { label: "threshold", value: formatScore(scoreRun.result?.threshold) },
          { label: "score run", value: String(scoreRun.result?.scoreRunId ?? "n/a") },
        ]
        : latestScoreRun
          ? [
            { label: "results", value: formatCount(state.settings.ledger.scoreResults.length) },
            { label: "latest asset", value: String(latestScoreResult?.immich_asset_id ?? "n/a") },
            { label: "score", value: formatScore(latestScoreResult?.total_score) },
          ]
          : [
            { label: "status", value: "idle" },
            { label: "waiting", value: "score review" },
          ],
    },
    {
      title: "Apply",
      jobRun: applyRun,
      fallbackActive: latestAction !== null,
      note: applyRun
        ? "threshold 以下の asset を Review Album へ送った結果です。"
        : latestAction
          ? "保存済み action log から直近の apply を可視化しています。"
          : "apply 実行後に action log がここへ反映されます。",
      facts: applyRun
        ? [
          { label: "applied", value: formatCount(applyRun.result?.appliedCount) },
          { label: "dry run", value: applyRun.result?.dryRun ? "yes" : "no" },
          { label: "threshold", value: formatScore(applyRun.result?.threshold) },
        ]
        : latestAction
          ? [
            { label: "actions", value: formatCount(state.settings.ledger.actionExecutionLogs.length) },
            { label: "latest action", value: String(latestAction.action_type ?? "n/a") },
            { label: "status", value: String(latestAction.status ?? "n/a") },
          ]
          : [
            { label: "status", value: "idle" },
            { label: "waiting", value: "action execution log" },
          ],
    },
  ];

  return stages.map((stage) => {
    if (stage.jobRun?.status === "failed") {
      return { ...stage, badge: "failed", tone: "is-failed" };
    }
    if (stage.jobRun !== null) {
      return { ...stage, badge: "completed", tone: "is-completed" };
    }
    if (stage.fallbackActive) {
      return { ...stage, badge: "persisted", tone: "is-persisted" };
    }
    return { ...stage, badge: "idle", tone: "is-idle" };
  });
};

const buildActivityFeedItems = () => {
  const jobItems = state.ui.jobHistory.slice(0, 6).map((jobRun) => ({
    at: jobRun.submittedAt,
    kind: `job / ${jobRun.jobType}`,
    title: formatJobResultSummary(jobRun),
    note: jobRun.status === "failed"
      ? String(jobRun.result?.errorType ?? "failed")
      : `submitted ${formatDateTime(jobRun.submittedAt)}`,
    tone: jobRun.status === "failed" ? "is-error" : "is-job",
  }));

  const traceItems = [...state.settings.ledger.inferenceTraces]
    .sort((left, right) => compareIsoTimestamp(left.occurred_at, right.occurred_at))
    .slice(0, 3)
    .map((trace) => ({
      at: trace.occurred_at,
      kind: "trace",
      title: `${String(trace.immich_asset_id ?? "asset")} / score ${formatScore(trace.final_score)}`,
      note: `candidates ${(trace.candidate_categories ?? []).join(", ") || "n/a"}`,
      tone: "is-trace",
    }));

  const actionItems = [...state.settings.ledger.actionExecutionLogs]
    .sort((left, right) => compareIsoTimestamp(left.executed_at, right.executed_at))
    .slice(0, 3)
    .map((actionLog) => ({
      at: actionLog.executed_at,
      kind: "action",
      title: `${String(actionLog.action_type ?? "action")} / ${String(actionLog.status ?? "unknown")}`,
      note: `${String(actionLog.immich_asset_id ?? "asset")} / ${actionLog.dry_run ? "dry run" : "write"}`,
      tone: actionLog.status === "failed" ? "is-error" : "is-action",
    }));

  return [...jobItems, ...traceItems, ...actionItems]
    .sort((left, right) => compareIsoTimestamp(left.at, right.at))
    .slice(0, 8);
};

const renderProcessVisualization = () => {
  const container = document.getElementById("process-visualization");
  if (!container) {
    return;
  }

  const latestModel = getLatestModelSnapshot();
  const latestScoreRun = getLatestScoreRun();
  const latestScoreResult = getLatestScoreResult();
  const latestAction = getLatestActionLog();
  const recentJob = state.ui.jobHistory[0] ?? null;
  const metricCards = [
    {
      label: "recent manual jobs",
      value: formatCount(state.ui.jobHistory.length),
      note: recentJob ? `${recentJob.jobType} / ${formatDateTime(recentJob.submittedAt)}` : "run a job from this console",
    },
    {
      label: "trained snapshots",
      value: formatCount(state.settings.models.length),
      note: latestModel ? `${String(latestModel.runId ?? "run")} / ${formatDateTime(latestModel.trainedAt)}` : "no snapshot yet",
    },
    {
      label: "score review rows",
      value: formatCount(state.settings.ledger.scoreResults.length),
      note: latestScoreRun ? `${String(latestScoreRun.id ?? "score-run")} / top ${String(latestScoreResult?.immich_asset_id ?? "n/a")}` : "no score run yet",
    },
    {
      label: "trash apply logs",
      value: formatCount(state.settings.ledger.actionExecutionLogs.length),
      note: latestAction ? `${String(latestAction.action_type ?? "action")} / ${String(latestAction.status ?? "unknown")}` : "no action yet",
    },
  ];
  const stages = buildStageCards();
  const activityItems = buildActivityFeedItems();

  container.innerHTML = `
    <article class="panel panel-wide process-summary">
      <div class="panel-header">
        <div>
          <h2>Process Overview</h2>
          <p class="panel-note">manual job の直近結果と、snapshot / ledger に残った派生結果を同じ面で追うためのビューです。</p>
        </div>
        <span class="summary-chip">${escapeHtml(recentJob ? `${recentJob.jobType} ${recentJob.status}` : "waiting for manual runs")}</span>
      </div>
      <div class="process-metrics">
        ${metricCards.map((item) => `
          <article class="metric-card">
            <p class="metric-label">${escapeHtml(item.label)}</p>
            <strong class="metric-value">${escapeHtml(item.value)}</strong>
            <p class="metric-note">${escapeHtml(item.note)}</p>
          </article>
        `).join("")}
      </div>
    </article>
    <article class="panel">
      <div class="panel-header">
        <div>
          <h2>Pipeline Stages</h2>
          <p class="panel-note">learn, score, apply を段ごとに見て、どこまで結果が出ているかを把握します。</p>
        </div>
      </div>
      <div class="stage-grid">
        ${stages.map((stage) => `
          <article class="stage-card ${escapeHtml(stage.tone)}">
            <div class="stage-header">
              <strong class="stage-name">${escapeHtml(stage.title)}</strong>
              <span class="process-badge">${escapeHtml(stage.badge)}</span>
            </div>
            <p class="stage-note">${escapeHtml(stage.note)}</p>
            <dl class="stage-facts">
              ${stage.facts.map((fact) => `
                <div>
                  <dt>${escapeHtml(fact.label)}</dt>
                  <dd>${escapeHtml(fact.value)}</dd>
                </div>
              `).join("")}
            </dl>
          </article>
        `).join("")}
      </div>
    </article>
    <article class="panel">
      <div class="panel-header">
        <div>
          <h2>Recent Activity</h2>
          <p class="panel-note">このブラウザで叩いた manual job と、保存済み trace / action の直近イベントです。</p>
        </div>
      </div>
      ${activityItems.length ? `
        <div class="activity-feed">
          ${activityItems.map((item) => `
            <article class="activity-item ${escapeHtml(item.tone)}">
              <div class="activity-meta">
                <span class="process-badge">${escapeHtml(item.kind)}</span>
                <time>${escapeHtml(formatDateTime(item.at))}</time>
              </div>
              <strong>${escapeHtml(item.title)}</strong>
              <p class="activity-note">${escapeHtml(item.note)}</p>
            </article>
          `).join("")}
        </div>
      ` : `
        <div class="empty-state">
          <p class="subtle">manual job を実行すると、この画面に stage ごとの結果と recent activity が積み上がります。</p>
        </div>
      `}
    </article>
  `;
};

const applyRouteState = () => {
  document.body.dataset.route = state.ui.currentRoute;
  if (state.ui.currentRoute === "settings") {
    document.title = "Smart Ranker Console / Settings";
  } else if (state.ui.currentRoute === "score-review") {
    document.title = "Smart Ranker Console / Score Review";
  } else {
    document.title = "Smart Ranker Console";
  }

  for (const link of document.querySelectorAll("[data-route-link]")) {
    const isCurrent = link.dataset.routeLink === state.ui.currentRoute;
    if (isCurrent) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  }
};

const optionHtml = (options, selectedValue) => options
  .map((option) => {
    const value = String(option.value);
    const selected = value === String(selectedValue ?? "") ? " selected" : "";
    return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(option.label)}</option>`;
  })
  .join("");

const normalizeMembers = (members) => (members ?? [])
  .filter((member) => member && member.immichPersonId)
  .map((member, index) => ({
    id: member.id ?? createTempId("member"),
    immichPersonId: String(member.immichPersonId),
    immichPersonName: String(member.immichPersonName ?? member.immichPersonId),
    sortOrder: index,
    enabled: member.enabled !== false,
  }));

const ensurePersonGroupSelection = () => {
  const personGroups = state.settings.personGroups ?? [];
  if (!personGroups.length) {
    state.ui.selectedPersonGroupKey = null;
    return;
  }

  const selectedExists = personGroups.some((group) => group.groupKey === state.ui.selectedPersonGroupKey);
  if (!selectedExists) {
    state.ui.selectedPersonGroupKey = personGroups[0].groupKey;
  }
};

const getSelectedPersonGroup = () => {
  ensurePersonGroupSelection();
  return state.settings.personGroups.find((group) => group.groupKey === state.ui.selectedPersonGroupKey) ?? null;
};

const updatePersonGroup = (groupKey, updater) => {
  state.settings.personGroups = state.settings.personGroups.map((group) => {
    if (group.groupKey !== groupKey) {
      return { ...group, members: normalizeMembers(group.members) };
    }

    const nextGroup = updater({ ...group, members: normalizeMembers(group.members) });
    return {
      ...nextGroup,
      members: normalizeMembers(nextGroup.members),
    };
  });
  ensurePersonGroupSelection();
};

const getReviewPolicy = () => state.settings.policies.find((policy) => policy.policyKey === DEFAULT_POLICY_KEY) ?? {
  policyKey: DEFAULT_POLICY_KEY,
  displayName: "Review Threshold Policy",
  executionMode: "manual",
  display: {
    reviewThreshold: DEFAULT_REVIEW_THRESHOLD,
    updateDescription: true,
  },
  enabled: true,
};

const getDestination = (destinationKey, fallback) => state.settings.destinations.find(
  (destination) => destination.destinationKey === destinationKey,
) ?? fallback;

const upsertByKey = (items, keyField, nextItem) => {
  const existingIndex = items.findIndex((item) => item[keyField] === nextItem[keyField]);
  if (existingIndex === -1) {
    return [...items, nextItem];
  }
  const nextItems = [...items];
  nextItems[existingIndex] = nextItem;
  return nextItems;
};

const defaultSchedules = () => ["learn", "score", "apply"].map((jobType) => ({
  id: createTempId(`schedule-${jobType}`),
  jobType,
  runMode: "manual",
  cronExpr: null,
  dryRun: jobType === "score",
  batchSize: 1000,
  enabled: true,
}));

const renderPersonGroupApp = () => {
  const container = document.getElementById("person-group-app");
  const personGroups = state.settings.personGroups ?? [];
  const selectedGroup = getSelectedPersonGroup();

  if (!personGroups.length || selectedGroup === null) {
    container.innerHTML = `
      <div class="empty-state">
        <p class="subtle">seed defaults を押して person group を作ると、ここで displayName を選びながら member を管理できます。</p>
      </div>
    `;
    return;
  }

  const replaceTarget = selectedGroup.members.find((member) => member.id === state.ui.personReplaceTarget);

  container.innerHTML = `
    <div class="group-layout">
      <div class="group-nav">
        ${personGroups.map((group) => `
          <button
            type="button"
            class="group-button${group.groupKey === selectedGroup.groupKey ? " is-active" : ""}"
            data-action="select-person-group"
            data-group-key="${escapeHtml(group.groupKey)}"
          >
            <strong>${escapeHtml(group.displayName)}</strong>
            <span>${escapeHtml(group.groupKey)} / ${(group.members ?? []).length} members</span>
          </button>
        `).join("")}
      </div>
      <div class="detail-surface">
        <div class="detail-header">
          <div>
            <p class="kicker">selected group</p>
            <h3>${escapeHtml(selectedGroup.displayName)}</h3>
            <p class="subtle">${escapeHtml(selectedGroup.groupKey)}</p>
          </div>
          <label class="toggle">
            <input
              type="checkbox"
              data-action="toggle-group-enabled"
              ${selectedGroup.enabled ? "checked" : ""}
            >
            group enabled
          </label>
        </div>

        <section class="settings-section">
          <div class="section-header compact">
            <h3>Members</h3>
            <span class="token">${selectedGroup.members.length} people</span>
          </div>
          ${selectedGroup.members.length ? `
            <div class="member-list">
              ${selectedGroup.members.map((member) => `
                <article class="member-card">
                  <div class="inline-actions">
                    <div>
                      <strong>${escapeHtml(member.immichPersonName || "Unnamed Person")}</strong>
                      <div class="member-meta">
                        <span class="meta-chip mono">${escapeHtml(member.immichPersonId)}</span>
                      </div>
                    </div>
                    <div class="inline-actions">
                      <label class="toggle">
                        <input
                          type="checkbox"
                          data-action="toggle-member-enabled"
                          data-member-id="${escapeHtml(member.id)}"
                          ${member.enabled ? "checked" : ""}
                        >
                        enabled
                      </label>
                      <button
                        type="button"
                        class="ghost-button"
                        data-action="replace-member"
                        data-member-id="${escapeHtml(member.id)}"
                      >
                        replace
                      </button>
                      <button
                        type="button"
                        class="icon-button"
                        data-action="remove-member"
                        data-member-id="${escapeHtml(member.id)}"
                      >
                        delete
                      </button>
                    </div>
                  </div>
                </article>
              `).join("")}
            </div>
          ` : `
            <div class="empty-state">
              <p class="subtle">まだ member がありません。下の検索から Immich Person を追加してください。</p>
            </div>
          `}
        </section>

        <section class="search-panel">
          <div class="section-header compact">
            <h3>Immich Person Search</h3>
            <span class="token">search result will be fetched live</span>
          </div>
          <div class="search-row">
            <input
              id="person-search-query"
              type="search"
              placeholder="Person 名で検索"
              value="${escapeHtml(state.ui.personSearchQuery)}"
            >
            <button type="button" data-action="search-people">search</button>
          </div>
          ${replaceTarget ? `
            <p class="inline-note">
              ${escapeHtml(replaceTarget.immichPersonName)} を差し替えます。
              <button type="button" class="ghost-button" data-action="cancel-replace">cancel</button>
            </p>
          ` : `
            <p class="subtle">検索結果を選ぶと ${escapeHtml(selectedGroup.displayName)} に追加します。</p>
          `}
          ${state.ui.personSearchResults.length ? `
            <div class="search-results">
              ${state.ui.personSearchResults.map((person) => `
                <article class="setting-card compact">
                  <div class="inline-actions">
                    <div>
                      <strong>${escapeHtml(person.name || "Unnamed Person")}</strong>
                      <div class="meta-row">
                        <span class="meta-chip mono">${escapeHtml(person.id)}</span>
                        ${person.faceAssetId ? `<span class="meta-chip">face ${escapeHtml(person.faceAssetId)}</span>` : ""}
                        ${person.isHidden ? `<span class="meta-chip">hidden</span>` : ""}
                      </div>
                    </div>
                    <button
                      type="button"
                      class="search-result-button"
                      data-action="apply-person-result"
                      data-person-id="${escapeHtml(person.id)}"
                    >
                      ${replaceTarget ? "replace with this" : "add member"}
                    </button>
                  </div>
                </article>
              `).join("")}
            </div>
          ` : ""}
        </section>
      </div>
    </div>
  `;
};

const renderCategoriesRoutingApp = () => {
  const container = document.getElementById("categories-routing-app");
  const categories = state.settings.categories ?? [];
  const routingRules = state.settings.routingRules ?? [];
  const personGroups = state.settings.personGroups ?? [];

  if (!categories.length) {
    container.innerHTML = `
      <div class="empty-state">
        <p class="subtle">seed defaults を押すと category と routing rule が入り、ここから UI で調整できます。</p>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <section class="settings-section">
      <div class="section-header">
        <div>
          <h3>Categories</h3>
          <p class="subtle">key は固定のまま、表示名や alias、enabled を調整します。</p>
        </div>
      </div>
      <div class="card-grid">
        ${categories.map((category) => `
          <article
            class="setting-card"
            data-kind="category-card"
            data-category-id="${escapeHtml(category.id || "")}" 
            data-category-key="${escapeHtml(category.categoryKey)}"
          >
            <div class="card-header">
              <strong>${escapeHtml(category.categoryKey)}</strong>
              <span class="token">${escapeHtml(category.categoryType)}</span>
            </div>
            <div class="field-grid">
              <label class="field">
                <span>Display Name</span>
                <input data-field="displayName" type="text" value="${escapeHtml(category.displayName)}">
              </label>
              <label class="field">
                <span>Aliases</span>
                <input data-field="aliases" type="text" value="${escapeHtml(joinCommaSeparated(category.aliases))}">
              </label>
              <label class="field">
                <span>Category Type</span>
                <select data-field="categoryType">
                  ${optionHtml(CATEGORY_TYPE_OPTIONS, category.categoryType)}
                </select>
              </label>
              <label class="field">
                <span>Media Scope</span>
                <select data-field="mediaScope">
                  ${optionHtml(MEDIA_SCOPE_OPTIONS, category.mediaScope)}
                </select>
              </label>
            </div>
            <div class="toggle-row">
              <label class="toggle">
                <input data-field="enabled" type="checkbox" ${category.enabled ? "checked" : ""}>
                enabled
              </label>
            </div>
          </article>
        `).join("")}
      </div>
    </section>
    <section class="settings-section">
      <div class="section-header">
        <div>
          <h3>Routing Rules</h3>
          <p class="subtle">rule ごとに category、mode、検索条件をカード単位で編集します。</p>
        </div>
        <button type="button" class="button-secondary" data-action="add-routing-rule">add rule</button>
      </div>
      <div class="schedule-grid">
        ${routingRules.map((rule) => {
          const assignmentMode = String(rule.assignmentMode || "mechanical");
          const match = rule.match ?? {};
          return `
            <article class="setting-card" data-kind="rule-card" data-rule-id="${escapeHtml(rule.id || createTempId("rule"))}">
              <div class="card-header">
                <strong>${escapeHtml(rule.ruleName)}</strong>
                <button type="button" class="icon-button" data-action="remove-routing-rule" data-rule-id="${escapeHtml(rule.id || "")}">delete</button>
              </div>
              <div class="field-grid">
                <label class="field">
                  <span>Rule Name</span>
                  <input data-field="ruleName" type="text" value="${escapeHtml(rule.ruleName)}">
                </label>
                <label class="field">
                  <span>Category</span>
                  <select data-field="categoryKey">
                    ${optionHtml(categories.map((category) => ({ value: category.categoryKey, label: `${category.displayName} (${category.categoryKey})` })), rule.categoryKey)}
                  </select>
                </label>
                <label class="field">
                  <span>Priority</span>
                  <input data-field="priority" type="number" value="${escapeHtml(rule.priority)}">
                </label>
                <label class="field">
                  <span>Mode</span>
                  <select data-field="assignmentMode">
                    ${optionHtml(ROUTING_MODE_OPTIONS, assignmentMode)}
                  </select>
                </label>
              </div>
              <div class="toggle-row">
                <label class="toggle">
                  <input data-field="enabled" type="checkbox" ${rule.enabled ? "checked" : ""}>
                  enabled
                </label>
                <label class="toggle">
                  <input data-field="stopAfterMatch" type="checkbox" ${rule.stopAfterMatch ? "checked" : ""}>
                  stop after match
                </label>
              </div>
              <div class="rule-mode-panel">
                ${assignmentMode === "person_group" ? `
                  <div class="field-grid single">
                    <label class="field">
                      <span>Person Group</span>
                      <select data-field="personGroupKey">
                        ${optionHtml(personGroups.map((group) => ({ value: group.groupKey, label: `${group.displayName} (${group.groupKey})` })), match.groupKey)}
                      </select>
                    </label>
                  </div>
                ` : ""}
                ${assignmentMode === "mechanical" ? `
                  <div class="field-grid single">
                    <label class="field">
                      <span>Source</span>
                      <select data-field="mechanicalSource">
                        ${optionHtml(MECHANICAL_SOURCE_OPTIONS, match.source)}
                      </select>
                    </label>
                    <label class="field">
                      <span>Keywords</span>
                      <input data-field="mechanicalKeywords" type="text" value="${escapeHtml(joinCommaSeparated(match.keywords))}">
                    </label>
                  </div>
                ` : ""}
                ${assignmentMode === "smart_search" ? `
                  <div class="field-grid single">
                    <label class="field">
                      <span>Queries</span>
                      <input data-field="smartQueries" type="text" value="${escapeHtml(joinCommaSeparated(match.queries))}">
                    </label>
                  </div>
                ` : ""}
                ${assignmentMode === "fallback" ? `
                  <p class="subtle">fallback rule は追加条件を持ちません。</p>
                ` : ""}
              </div>
            </article>
          `;
        }).join("")}
      </div>
    </section>
  `;
};

const renderPoliciesApp = () => {
  const container = document.getElementById("policies-app");
  const reviewPolicy = getReviewPolicy();

  container.innerHTML = `
    <section class="settings-section">
      <div class="field-grid">
        <label class="field">
          <span>Policy Name</span>
          <input id="policy-display-name" type="text" value="${escapeHtml(reviewPolicy.displayName)}">
        </label>
        <label class="field">
          <span>Execution Mode</span>
          <select id="policy-execution-mode">
            <option value="manual"${reviewPolicy.executionMode === "manual" ? " selected" : ""}>manual</option>
          </select>
        </label>
        <label class="field">
          <span>Trash Threshold</span>
          <input id="policy-review-threshold" type="number" min="0" max="1" step="0.01" value="${escapeHtml(reviewPolicy.display?.reviewThreshold ?? DEFAULT_REVIEW_THRESHOLD)}">
        </label>
      </div>
      <div class="toggle-row">
        <label class="toggle">
          <input id="policy-enabled" type="checkbox" ${reviewPolicy.enabled ? "checked" : ""}>
          threshold policy enabled
        </label>
      </div>
    </section>
  `;
};

const renderJobsModelsApp = () => {
  const container = document.getElementById("jobs-models-app");
  const schedules = state.settings.schedules.length ? state.settings.schedules : defaultSchedules();
  state.settings.schedules = schedules;

  container.innerHTML = `
    <section class="settings-section">
      <div class="schedule-grid">
        ${schedules.map((schedule) => `
          <article class="setting-card" data-kind="schedule-card" data-schedule-id="${escapeHtml(schedule.id || createTempId("schedule"))}" data-job-type="${escapeHtml(schedule.jobType)}">
            <div class="card-header">
              <strong>${escapeHtml(schedule.jobType)}</strong>
              <span class="token">job</span>
            </div>
            <div class="field-grid">
              <label class="field">
                <span>Run Mode</span>
                <select data-field="runMode">
                  ${optionHtml(SCHEDULE_MODE_OPTIONS, schedule.runMode)}
                </select>
              </label>
              <label class="field">
                <span>Batch Size</span>
                <input data-field="batchSize" type="number" min="1" value="${escapeHtml(schedule.batchSize)}">
              </label>
              <label class="field">
                <span>Cron Expr</span>
                <input data-field="cronExpr" type="text" value="${escapeHtml(schedule.cronExpr || "")}" placeholder="optional">
              </label>
            </div>
            <div class="toggle-row">
              <label class="toggle">
                <input data-field="enabled" type="checkbox" ${schedule.enabled ? "checked" : ""}>
                enabled
              </label>
              <label class="toggle">
                <input data-field="dryRun" type="checkbox" ${schedule.dryRun ? "checked" : ""}>
                dry run
              </label>
            </div>
          </article>
        `).join("")}
      </div>
    </section>
  `;
};

const renderDerivedLists = () => {
  renderList("models", state.settings.models, (item) => {
    const modelKeys = (item.models ?? []).map((model) => model.model_key ?? "unknown").join(", ");
    return `${item.runId ?? "no-run"} @ ${item.trainedAt ?? "n/a"}${modelKeys ? ` / ${modelKeys}` : ""}`;
  });
  renderList(
    "ledger-feedback",
    [
      ...(state.settings.ledger.favoriteSignals ?? []).map((item) => ({ ...item, signalType: "favorite" })),
      ...(state.settings.ledger.trashSignals ?? []).map((item) => ({ ...item, signalType: "trash" })),
    ],
    (item) => `${item.signalType} / ${item.immich_asset_id}`,
  );
  renderList(
    "ledger-traces",
    state.settings.ledger.scoreResults.slice(0, 8),
    (item) => `#${item.rank_index} / ${item.immich_asset_id} / ${formatScore(item.total_score)}`,
  );
  renderList("ledger-actions", state.settings.ledger.actionExecutionLogs, (item) => `${item.action_type} / ${item.status}`);

  const exclusionList = document.getElementById("ledger-exclusions");
  if (exclusionList) {
    const activeExclusions = [...(state.settings.ledger.applyExclusionAssets ?? [])]
      .filter((item) => Number(item.active) === 1)
      .sort((left, right) => compareIsoTimestamp(left.excluded_at, right.excluded_at));

    exclusionList.innerHTML = activeExclusions.length
      ? activeExclusions.map((item) => `
        <li>
          <span>${escapeHtml(String(item.immich_asset_id ?? "asset"))}</span>
          <button
            type="button"
            class="button-secondary"
            data-action="clear-apply-exclusion"
            data-asset-id="${escapeHtml(String(item.immich_asset_id ?? ""))}"
          >allow reapply</button>
        </li>
      `).join("")
      : '<li class="subtle">no active reapply suppression</li>';
  }
};

const renderScoreReviewPage = () => {
  const container = document.getElementById("score-review-page");
  if (!container) {
    return;
  }

  const scoreReview = state.ui.scoreReview;
  const items = scoreReview.items ?? [];
  const sortOrder = normalizeScoreReviewSortOrder(scoreReview.sortOrder);
  if (!scoreReview.scoreRunId) {
    container.innerHTML = `
      <article class="panel score-review-empty">
        <p class="eyebrow">Score Review</p>
        <h1>Scored assets will appear here after score completes.</h1>
        <p class="lede">latest completed score run がない場合は一覧を作れません。先に score を実行してください。</p>
      </article>
    `;
    return;
  }

  const scoreRun = scoreReview.scoreRun ?? {};
  const totalPages = Math.max(1, Number(scoreReview.totalPages) || 1);
  const cardsHtml = items.length
    ? items.map((item) => {
      const currentState = item.currentState ?? {};
      const originalPath = currentState.originalPath || currentState.original_path || "";
      const originalFileName = currentState.originalFileName || currentState.original_file_name || getFileName(originalPath) || item.immichAssetId;
      const categoryEntries = Object.entries(item.categoryScores ?? {})
        .sort((left, right) => Number(right[1]) - Number(left[1]))
        .slice(0, 3);
      const badges = [];
      if (currentState.isFavorite || currentState.is_favorite) {
        badges.push('<span class="meta-chip">favorite</span>');
      }
      if (currentState.isTrashed || currentState.is_trashed) {
        badges.push('<span class="meta-chip">trash</span>');
      }
      if (currentState.type) {
        badges.push(`<span class="meta-chip">${escapeHtml(currentState.type)}</span>`);
      }
      return `
        <article class="panel score-review-card">
          <div class="score-review-card-media">
            <img
              class="score-review-thumb"
              src="${escapeHtml(item.thumbnailUrl)}"
              alt="${escapeHtml(originalFileName)} thumbnail"
              loading="lazy"
              referrerpolicy="same-origin"
            >
          </div>
          <div class="score-review-card-body">
            <div class="score-review-card-head">
              <span class="token">#${formatCount(item.rankIndex)}</span>
              <strong class="score-review-score">${escapeHtml(formatScore(item.totalScore))}</strong>
            </div>
            <div>
              <h3>${escapeHtml(originalFileName)}</h3>
              <p class="subtle">${escapeHtml(item.immichAssetId)}</p>
            </div>
            <p class="subtle score-review-path">${escapeHtml(originalPath || "path unavailable")}</p>
            <div class="score-review-card-foot">
              <div class="meta-row">
                ${badges.join("")}
                ${categoryEntries.map(([key, value]) => `<span class="meta-chip">${escapeHtml(key)} ${escapeHtml(formatScore(value))}</span>`).join("")}
              </div>
            </div>
          </div>
        </article>
      `;
    }).join("")
    : `
      <article class="panel score-review-empty">
        <p class="subtle">この score run に score result はありません。</p>
      </article>
    `;

  container.innerHTML = `
    <article class="panel">
      <p class="eyebrow">Score Review</p>
      <div class="score-review-toolbar">
        <div>
          <h1>Scored assets ordered for review.</h1>
          <p class="lede">score の結果をカードで 100 件ずつ確認します。thumbnail は Immich API を backend 経由で取得します。</p>
        </div>
        <div class="score-review-toolbar-actions">
          <div class="score-review-sorter" role="group" aria-label="Score review sort order">
            <button type="button" class="button-secondary score-review-sort-button" data-action="score-review-sort" data-sort-order="asc" aria-pressed="${sortOrder === "asc"}">score low -&gt; high</button>
            <button type="button" class="button-secondary score-review-sort-button" data-action="score-review-sort" data-sort-order="desc" aria-pressed="${sortOrder === "desc"}">score high -&gt; low</button>
          </div>
          <div class="score-review-pager">
            <button type="button" class="button-secondary" data-action="score-review-prev" ${scoreReview.page <= 1 ? "disabled" : ""}>prev 100</button>
            <form class="score-review-page-jump" data-role="score-review-page-jump">
              <label class="score-review-page-field">
                <span>page</span>
                <input
                  class="score-review-page-input"
                  type="number"
                  min="1"
                  max="${totalPages}"
                  step="1"
                  inputmode="numeric"
                  value="${scoreReview.page}"
                  data-role="score-review-page-input"
                  ${scoreReview.totalPages === 0 ? "disabled" : ""}
                >
              </label>
              <button type="submit" class="button-secondary" ${scoreReview.totalPages === 0 ? "disabled" : ""}>go</button>
            </form>
            <button type="button" class="button-secondary" data-action="score-review-next" ${scoreReview.totalPages === 0 || scoreReview.page >= scoreReview.totalPages ? "disabled" : ""}>next 100</button>
          </div>
        </div>
      </div>
      <div class="score-review-summary">
        <div class="meta-row">
          <span class="summary-chip">run ${escapeHtml(String(scoreRun.id ?? scoreReview.scoreRunId).slice(0, 8))}</span>
          <span class="summary-chip">items ${escapeHtml(formatScoreReviewRange())}</span>
          <span class="summary-chip">page ${escapeHtml(formatCount(scoreReview.page))} / ${escapeHtml(formatCount(scoreReview.totalPages))}</span>
          <span class="summary-chip">sort ${escapeHtml(formatScoreReviewSortLabel(sortOrder))}</span>
        </div>
        <p class="subtle">completed ${escapeHtml(formatDateTime(scoreRun.completedAt))}</p>
      </div>
    </article>
    <section class="score-review-grid">
      ${cardsHtml}
    </section>
  `;
};

const renderAll = () => {
  applyRouteState();
  ensurePersonGroupSelection();
  renderJobOutput();
  renderProcessVisualization();
  renderScoreReviewPage();
  renderPersonGroupApp();
  renderCategoriesRoutingApp();
  renderPoliciesApp();
  renderJobsModelsApp();
  renderDerivedLists();
};

const refresh = async () => {
  const [personGroupSettings, categoriesRoutingSettings, policySettings, jobsModels, ledger, scoreReviewPayload] = await Promise.all([
    fetchJson("/api/settings/person-groups"),
    fetchJson("/api/settings/categories-routing"),
    fetchJson("/api/settings/policies"),
    fetchJson("/api/settings/jobs-models"),
    fetchJson("/api/event-ledger"),
    state.ui.currentRoute === "score-review" ? loadScoreReviewPage(state.ui.scoreReview.page) : Promise.resolve(null),
  ]);

  syncJobHistoryWithRuntimeResetToken(jobsModels.runtimeResetToken);

  state.settings.personGroups = (personGroupSettings.personGroups ?? []).map((group) => ({
    ...group,
    members: normalizeMembers(group.members),
  }));
  state.settings.categories = categoriesRoutingSettings.categories ?? [];
  state.settings.routingRules = categoriesRoutingSettings.routingRules ?? [];
  state.settings.policies = policySettings.policies ?? [];
  state.settings.destinations = policySettings.destinations ?? [];
  state.settings.schedules = jobsModels.schedules ?? [];
  state.settings.models = jobsModels.models ?? [];
  state.settings.ledger = ledger;
  if (scoreReviewPayload) {
    setStatus(
      "score-review-status",
      state.ui.scoreReview.totalItems
        ? `showing ${formatScoreReviewRange()}`
        : "score result not available yet",
    );
  }
  renderAll();
};

const installScoreReviewHandlers = () => {
  const container = document.getElementById("score-review-page");
  if (!container) {
    return;
  }

  container.addEventListener("click", async (event) => {
    const control = event.target.closest("[data-action]");
    if (!control) {
      return;
    }

    const action = control.dataset.action;
    let nextPage = state.ui.scoreReview.page;

    if (action === "score-review-sort") {
      const nextSortOrder = normalizeScoreReviewSortOrder(control.dataset.sortOrder);
      if (nextSortOrder === state.ui.scoreReview.sortOrder) {
        return;
      }
      state.ui.scoreReview.sortOrder = nextSortOrder;
      nextPage = 1;
    } else if (action === "score-review-prev") {
      nextPage = state.ui.scoreReview.page - 1;
    } else if (action === "score-review-next") {
      nextPage = state.ui.scoreReview.page + 1;
    } else {
      return;
    }

    try {
      await reloadScoreReviewPage(nextPage);
    } catch (error) {
      setStatus("score-review-status", error instanceof Error ? error.message : String(error), true);
    }
  });

  container.addEventListener("submit", async (event) => {
    const form = event.target.closest('[data-role="score-review-page-jump"]');
    if (!form) {
      return;
    }

    event.preventDefault();

    const input = form.querySelector('[data-role="score-review-page-input"]');
    const nextPage = resolveScoreReviewTargetPage(input?.value);
    if (nextPage === null) {
      setStatus(
        "score-review-status",
        `page must be a number between 1 and ${formatCount(Math.max(1, Number(state.ui.scoreReview.totalPages) || 1))}`,
        true,
      );
      if (input) {
        input.value = String(state.ui.scoreReview.page);
      }
      return;
    }

    if (input) {
      input.value = String(nextPage);
    }

    if (nextPage === state.ui.scoreReview.page) {
      renderScoreReviewStatus();
      return;
    }

    try {
      await reloadScoreReviewPage(nextPage);
    } catch (error) {
      setStatus("score-review-status", error instanceof Error ? error.message : String(error), true);
    }
  });
};

const normalizeRuleForMode = (rule, assignmentMode) => {
  if (assignmentMode === "person_group") {
    return {
      ...rule,
      assignmentMode,
      match: {
        type: "person_group",
        groupKey: rule.match?.groupKey || state.settings.personGroups[0]?.groupKey || "family",
      },
    };
  }
  if (assignmentMode === "smart_search") {
    return {
      ...rule,
      assignmentMode,
      match: {
        type: "smart_search",
        queries: Array.isArray(rule.match?.queries) ? rule.match.queries : [],
      },
    };
  }
  if (assignmentMode === "fallback") {
    return {
      ...rule,
      assignmentMode,
      match: { type: "fallback" },
    };
  }
  return {
    ...rule,
    assignmentMode: "mechanical",
    match: {
      type: "mechanical",
      source: rule.match?.source || "ocr_text",
      keywords: Array.isArray(rule.match?.keywords) ? rule.match.keywords : [],
    },
  };
};

const syncCategoriesRoutingStateFromDom = () => {
  const container = document.getElementById("categories-routing-app");
  const categoryCards = [...container.querySelectorAll('[data-kind="category-card"]')];
  const ruleCards = [...container.querySelectorAll('[data-kind="rule-card"]')];

  state.settings.categories = categoryCards.map((card) => ({
    id: card.dataset.categoryId || undefined,
    categoryKey: card.dataset.categoryKey,
    displayName: card.querySelector('[data-field="displayName"]').value.trim() || card.dataset.categoryKey,
    aliases: splitCommaSeparated(card.querySelector('[data-field="aliases"]').value),
    categoryType: card.querySelector('[data-field="categoryType"]').value,
    mediaScope: card.querySelector('[data-field="mediaScope"]').value,
    enabled: card.querySelector('[data-field="enabled"]').checked,
  }));

  state.settings.routingRules = ruleCards.map((card, index) => {
    const assignmentMode = card.querySelector('[data-field="assignmentMode"]').value;
    let match = { type: assignmentMode };
    if (assignmentMode === "person_group") {
      match = {
        type: "person_group",
        groupKey: card.querySelector('[data-field="personGroupKey"]').value,
      };
    } else if (assignmentMode === "smart_search") {
      match = {
        type: "smart_search",
        queries: splitCommaSeparated(card.querySelector('[data-field="smartQueries"]').value),
      };
    } else if (assignmentMode === "fallback") {
      match = { type: "fallback" };
    } else {
      match = {
        type: "mechanical",
        source: card.querySelector('[data-field="mechanicalSource"]').value,
        keywords: splitCommaSeparated(card.querySelector('[data-field="mechanicalKeywords"]').value),
      };
    }

    return {
      id: card.dataset.ruleId || createTempId("rule"),
      categoryKey: card.querySelector('[data-field="categoryKey"]').value,
      ruleName: card.querySelector('[data-field="ruleName"]').value.trim() || `rule-${index + 1}`,
      priority: Number(card.querySelector('[data-field="priority"]').value) || 100,
      assignmentMode,
      stopAfterMatch: card.querySelector('[data-field="stopAfterMatch"]').checked,
      enabled: card.querySelector('[data-field="enabled"]').checked,
      match,
    };
  });
};

const syncPoliciesStateFromDom = () => {
  const reviewPolicy = getReviewPolicy();

  const nextPolicy = {
    ...reviewPolicy,
    displayName: document.getElementById("policy-display-name").value.trim() || "Review Threshold Policy",
    executionMode: document.getElementById("policy-execution-mode").value,
    enabled: document.getElementById("policy-enabled").checked,
    display: {
      ...reviewPolicy.display,
      reviewThreshold: Number(document.getElementById("policy-review-threshold").value) || DEFAULT_REVIEW_THRESHOLD,
      updateDescription: false,
    },
  };

  state.settings.policies = upsertByKey(state.settings.policies, "policyKey", nextPolicy);
};

const syncSchedulesStateFromDom = () => {
  const cards = [...document.querySelectorAll('#jobs-models-app [data-kind="schedule-card"]')];
  state.settings.schedules = cards.map((card) => ({
    id: card.dataset.scheduleId || createTempId("schedule"),
    jobType: card.dataset.jobType,
    runMode: card.querySelector('[data-field="runMode"]').value,
    cronExpr: card.querySelector('[data-field="cronExpr"]').value.trim() || null,
    dryRun: card.querySelector('[data-field="dryRun"]').checked,
    batchSize: Number(card.querySelector('[data-field="batchSize"]').value) || 1000,
    enabled: card.querySelector('[data-field="enabled"]').checked,
  }));
};

const savePersonGroups = async () => {
  const response = await fetchJson("/api/settings/person-groups", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ personGroups: state.settings.personGroups }),
  });
  setStatus("person-groups-status", `saved ${response.personGroups.length} groups`);
  await refresh();
};

const saveCategoriesRouting = async () => {
  syncCategoriesRoutingStateFromDom();
  const response = await fetchJson("/api/settings/categories-routing", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      categories: state.settings.categories,
      routingRules: state.settings.routingRules,
    }),
  });
  setStatus(
    "categories-routing-status",
    `saved ${response.categories.length} categories / ${response.routingRules.length} rules`,
  );
  await refresh();
};

const savePolicies = async () => {
  syncPoliciesStateFromDom();
  const response = await fetchJson("/api/settings/policies", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      policies: state.settings.policies,
      destinations: state.settings.destinations,
    }),
  });
  setStatus(
    "policies-status",
    `saved ${response.policies.length} policies / ${response.destinations.length} destinations`,
  );
  await refresh();
};

const saveSchedules = async () => {
  syncSchedulesStateFromDom();
  const response = await fetchJson("/api/settings/schedules", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ schedules: state.settings.schedules }),
  });
  setStatus("jobs-models-status", `saved ${response.schedules.length} schedules`);
  await refresh();
};

const saveHandlers = {
  "person-groups": savePersonGroups,
  "categories-routing": saveCategoriesRouting,
  policies: savePolicies,
  schedules: saveSchedules,
};

const saveStatusIds = {
  "person-groups": "person-groups-status",
  "categories-routing": "categories-routing-status",
  policies: "policies-status",
  schedules: "jobs-models-status",
};

const searchPeople = async () => {
  const queryInput = document.getElementById("person-search-query");
  state.ui.personSearchQuery = queryInput?.value?.trim() ?? state.ui.personSearchQuery;
  const params = new URLSearchParams({ limit: "16" });
  if (state.ui.personSearchQuery) {
    params.set("q", state.ui.personSearchQuery);
  }
  setStatus("person-groups-status", "searching Immich people...");
  const response = await fetchJson(`/api/immich/people?${params.toString()}`);
  state.ui.personSearchResults = response.items ?? [];
  setStatus(
    "person-groups-status",
    state.ui.personSearchResults.length ? `found ${state.ui.personSearchResults.length} people` : "no people found",
  );
  renderPersonGroupApp();
};

const applySelectedPerson = (personId) => {
  const selectedGroup = getSelectedPersonGroup();
  const person = state.ui.personSearchResults.find((item) => item.id === personId);
  if (selectedGroup === null || !person) {
    return;
  }

  const existingMember = selectedGroup.members.find((member) => member.immichPersonId === person.id);
  if (existingMember && existingMember.id !== state.ui.personReplaceTarget) {
    setStatus("person-groups-status", `${person.name || person.id} is already in ${selectedGroup.displayName}`, true);
    return;
  }

  updatePersonGroup(selectedGroup.groupKey, (group) => {
    const nextMembers = [...group.members];
    if (state.ui.personReplaceTarget) {
      const targetIndex = nextMembers.findIndex((member) => member.id === state.ui.personReplaceTarget);
      if (targetIndex >= 0) {
        nextMembers[targetIndex] = {
          ...nextMembers[targetIndex],
          immichPersonId: person.id,
          immichPersonName: person.name || person.id,
          enabled: true,
        };
      }
    } else {
      nextMembers.push({
        id: createTempId("member"),
        immichPersonId: person.id,
        immichPersonName: person.name || person.id,
        enabled: true,
      });
    }
    return { ...group, members: nextMembers };
  });

  state.ui.personReplaceTarget = null;
  setStatus("person-groups-status", `${person.name || person.id} was assigned to ${selectedGroup.displayName}`);
  renderPersonGroupApp();
};

const installPersonGroupHandlers = () => {
  const container = document.getElementById("person-group-app");

  container.addEventListener("click", async (event) => {
    const control = event.target.closest("[data-action]");
    if (!control) {
      return;
    }

    const action = control.dataset.action;
    try {
      if (action === "select-person-group") {
        state.ui.selectedPersonGroupKey = control.dataset.groupKey;
        state.ui.personReplaceTarget = null;
        renderPersonGroupApp();
        return;
      }

      if (action === "search-people") {
        await searchPeople();
        return;
      }

      if (action === "apply-person-result") {
        applySelectedPerson(control.dataset.personId);
        return;
      }

      if (action === "replace-member") {
        state.ui.personReplaceTarget = control.dataset.memberId;
        renderPersonGroupApp();
        return;
      }

      if (action === "cancel-replace") {
        state.ui.personReplaceTarget = null;
        renderPersonGroupApp();
        return;
      }

      if (action === "remove-member") {
        const selectedGroup = getSelectedPersonGroup();
        if (selectedGroup === null) {
          return;
        }
        updatePersonGroup(selectedGroup.groupKey, (group) => ({
          ...group,
          members: group.members.filter((member) => member.id !== control.dataset.memberId),
        }));
        if (state.ui.personReplaceTarget === control.dataset.memberId) {
          state.ui.personReplaceTarget = null;
        }
        setStatus("person-groups-status", "member removed");
        renderPersonGroupApp();
      }
    } catch (error) {
      setStatus("person-groups-status", error instanceof Error ? error.message : String(error), true);
    }
  });

  container.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) {
      return;
    }

    const action = target.dataset.action;
    const selectedGroup = getSelectedPersonGroup();
    if (selectedGroup === null) {
      return;
    }

    if (action === "toggle-group-enabled") {
      updatePersonGroup(selectedGroup.groupKey, (group) => ({ ...group, enabled: target.checked }));
      return;
    }

    if (action === "toggle-member-enabled") {
      updatePersonGroup(selectedGroup.groupKey, (group) => ({
        ...group,
        members: group.members.map((member) => (
          member.id === target.dataset.memberId ? { ...member, enabled: target.checked } : member
        )),
      }));
    }
  });

  container.addEventListener("input", (event) => {
    const target = event.target;
    if (target instanceof HTMLInputElement && target.id === "person-search-query") {
      state.ui.personSearchQuery = target.value;
    }
  });

  container.addEventListener("keydown", async (event) => {
    const target = event.target;
    if (target instanceof HTMLInputElement && target.id === "person-search-query" && event.key === "Enter") {
      event.preventDefault();
      try {
        await searchPeople();
      } catch (error) {
        setStatus("person-groups-status", error instanceof Error ? error.message : String(error), true);
      }
    }
  });
};

const installCategoriesRoutingHandlers = () => {
  const container = document.getElementById("categories-routing-app");
  container.addEventListener("click", (event) => {
    const control = event.target.closest("[data-action]");
    if (!control) {
      return;
    }

    const action = control.dataset.action;
    if (action === "add-routing-rule") {
      syncCategoriesRoutingStateFromDom();
      state.settings.routingRules.push({
        id: createTempId("rule"),
        categoryKey: state.settings.categories[0]?.categoryKey || "other",
        ruleName: `rule-${state.settings.routingRules.length + 1}`,
        priority: 100,
        assignmentMode: "mechanical",
        stopAfterMatch: false,
        enabled: true,
        match: {
          type: "mechanical",
          source: "ocr_text",
          keywords: [],
        },
      });
      renderCategoriesRoutingApp();
      return;
    }

    if (action === "remove-routing-rule") {
      syncCategoriesRoutingStateFromDom();
      state.settings.routingRules = state.settings.routingRules.filter((rule) => rule.id !== control.dataset.ruleId);
      renderCategoriesRoutingApp();
    }
  });

  container.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement) && !(target instanceof HTMLInputElement)) {
      return;
    }

    if (target.dataset.field === "assignmentMode") {
      const ruleCard = target.closest('[data-kind="rule-card"]');
      if (!ruleCard) {
        return;
      }
      syncCategoriesRoutingStateFromDom();
      state.settings.routingRules = state.settings.routingRules.map((rule) => (
        rule.id === ruleCard.dataset.ruleId ? normalizeRuleForMode(rule, target.value) : rule
      ));
      renderCategoriesRoutingApp();
    }
  });
};

const installSaveButtons = () => {
  for (const button of document.querySelectorAll("[data-save]")) {
    button.addEventListener("click", async () => {
      const saveTarget = button.dataset.save;
      const handler = saveHandlers[saveTarget];
      if (!handler) {
        return;
      }
      const statusId = saveStatusIds[saveTarget];
      try {
        setStatus(statusId, "saving...");
        await handler();
      } catch (error) {
        setStatus(statusId, error instanceof Error ? error.message : String(error), true);
      }
    });
  }
};

const installSeedButton = () => {
  const button = document.getElementById("seed-defaults");
  button.addEventListener("click", async () => {
    try {
      setStatus("global-status", "seeding default master data...");
      const payload = await fetchJson("/api/settings/seed-defaults", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      setStatus(
        "global-status",
        `seeded ${payload.personGroups.length} groups / ${payload.categories.length} categories / ${payload.routingRules.length} rules`,
      );
      await refresh();
    } catch (error) {
      setStatus("global-status", error instanceof Error ? error.message : String(error), true);
    }
  });
};

const installJobButtons = () => {
  const buttons = [...document.querySelectorAll("[data-job]")];
  for (const button of document.querySelectorAll("[data-job]")) {
    button.addEventListener("click", async () => {
      const jobType = button.dataset.job;
      try {
        for (const control of buttons) {
          control.disabled = true;
        }
        setStatus("global-status", `running ${jobType}...`);
        const accepted = await fetchJson(`/api/jobs/${jobType}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ trigger: "manual-ui" }),
        });
        const jobRun = await fetchJson(`/api/jobs/${accepted.jobRunId}`);
        rememberJobRun(jobRun);
        renderJobOutput(jobRun);
        setStatus(
          "global-status",
          jobRun.status === "failed"
            ? `${jobType} failed: ${formatJobResultSummary(jobRun)}`
            : `${jobType} completed: ${formatJobResultSummary(jobRun)}`,
          jobRun.status === "failed",
        );
        await refresh();
      } catch (error) {
        renderJobOutput({
          jobRunId: `error-${Date.now()}`,
          jobType,
          status: "failed",
          submittedAt: new Date().toISOString(),
          payload: { trigger: "manual-ui" },
          result: {
            error: error instanceof Error ? error.message : String(error),
            errorType: "ConsoleRequestError",
          },
        });
        setStatus("global-status", error instanceof Error ? error.message : String(error), true);
      } finally {
        for (const control of buttons) {
          control.disabled = false;
        }
      }
    });
  }
};

const installLedgerHandlers = () => {
  const container = document.querySelector(".panel-grid");
  if (!container) {
    return;
  }

  container.addEventListener("click", async (event) => {
    const control = event.target.closest("[data-action]");
    if (!control || control.dataset.action !== "clear-apply-exclusion") {
      return;
    }

    const assetId = String(control.dataset.assetId || "").trim();
    if (!assetId) {
      return;
    }

    try {
      control.disabled = true;
      setStatus("global-status", `clearing reapply suppression for ${assetId}...`);
      const payload = await fetchJson(`/api/apply-exclusions/${encodeURIComponent(assetId)}/clear`, {
        method: "POST",
      });
      const clearedCount = Number(payload.clearedCount) || 0;
      setStatus(
        "global-status",
        clearedCount
          ? `reapply enabled for ${assetId}`
          : `no active reapply suppression for ${assetId}`,
      );
      await refresh();
    } catch (error) {
      setStatus("global-status", error instanceof Error ? error.message : String(error), true);
    } finally {
      control.disabled = false;
    }
  });
};

installJobButtons();
installSaveButtons();
installSeedButton();
installPersonGroupHandlers();
installCategoriesRoutingHandlers();
installLedgerHandlers();
installScoreReviewHandlers();
startLiveReload();
refresh().catch((error) => {
  setStatus("score-review-status", error instanceof Error ? error.message : String(error), true);
  setStatus("global-status", error instanceof Error ? error.message : String(error), true);
});
