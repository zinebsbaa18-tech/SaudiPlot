// Backend API client for the frozen frontend journey.
//
// Every call goes to our own backend (VITE_API_BASE_URL); no AI-provider key
// ever exists in the browser. Cookies carry the anonymous session, so all
// requests use credentials: "include".

// When VITE_API_BASE_URL is empty-string, use relative URLs so the Vite dev
// server proxy (configured in vite.config.js) forwards /api/* to the backend.
// The empty-string check is intentional: "" is falsy in JS so the plain
// `|| "http://localhost:8000"` fallback would silently break on Replit.
const _rawBase = import.meta.env.VITE_API_BASE_URL;
const API_BASE = (_rawBase !== undefined && _rawBase !== "")
  ? _rawBase.replace(/\/$/, "")
  : "";

const PROJECT_ID_KEY = "spd_project_id";
const RUN_ID_KEY = "spd_run_id";

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message || code || `HTTP ${status}`);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request(path, { method = "GET", json, formData } = {}) {
  const options = { method, credentials: "include", headers: {} };
  if (json !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(json);
  }
  if (formData !== undefined) {
    options.body = formData;
  }
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, options);
  } catch {
    throw new ApiError(0, "backend_unreachable", "تعذر الاتصال بالخادم. تأكد من تشغيل الخادم المحلي.");
  }
  if (!response.ok) {
    let body = null;
    try {
      body = await response.json();
    } catch {
      /* non-JSON error body */
    }
    const error = body && body.error ? body.error : {};
    throw new ApiError(response.status, error.code, error.message, error.details);
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response;
}

// ── Session / project lifecycle ─────────────────────────────────────────

export async function ensureSession() {
  try {
    return await request("/api/v1/sessions/current");
  } catch (error) {
    if (error.status === 401) {
      return request("/api/v1/sessions", { method: "POST" });
    }
    throw error;
  }
}

export function storedProjectId() {
  return localStorage.getItem(PROJECT_ID_KEY) || null;
}

export function storedRunId() {
  return localStorage.getItem(RUN_ID_KEY) || null;
}

export function rememberRunId(runId) {
  if (runId) localStorage.setItem(RUN_ID_KEY, runId);
}

export async function ensureProject() {
  await ensureSession();
  const existing = storedProjectId();
  if (existing) {
    try {
      return await request(`/api/v1/projects/${existing}`);
    } catch (error) {
      // A stale id (expired session, wiped database) starts a fresh project.
      if (error.status !== 404) throw error;
      localStorage.removeItem(PROJECT_ID_KEY);
      localStorage.removeItem(RUN_ID_KEY);
    }
  }
  const project = await request("/api/v1/projects", {
    method: "POST",
    json: { current_step: "upload" },
  });
  localStorage.setItem(PROJECT_ID_KEY, project.id);
  return project;
}

export function updateProjectStep(projectId, currentStep) {
  return request(`/api/v1/projects/${projectId}`, {
    method: "PATCH",
    json: { current_step: currentStep },
  }).catch(() => null); // step tracking is best-effort
}

// ── Deed documents ──────────────────────────────────────────────────────

export async function uploadDeed(projectId, file) {
  const formData = new FormData();
  formData.append("file", file);
  return request(`/api/v1/projects/${projectId}/documents`, { method: "POST", formData });
}

// ── Plot / brief / room program / character ─────────────────────────────

export function savePlot(projectId, plot) {
  return request(`/api/v1/projects/${projectId}/plot`, { method: "PUT", json: plot });
}

export function getPlot(projectId) {
  return request(`/api/v1/projects/${projectId}/plot`);
}

export function saveBrief(projectId, answers) {
  return request(`/api/v1/projects/${projectId}/design-brief`, {
    method: "PUT",
    json: { answers },
  });
}

export function getBrief(projectId) {
  return request(`/api/v1/projects/${projectId}/design-brief`);
}

export function saveRoomProgram(projectId, counts) {
  return request(`/api/v1/projects/${projectId}/room-program`, {
    method: "PUT",
    json: { counts },
  });
}

export function resolveCharacter(projectId) {
  return request(`/api/v1/projects/${projectId}/resolve-character`, { method: "POST" });
}

// ── Design runs ─────────────────────────────────────────────────────────

export function startDesignRun(projectId) {
  return request(`/api/v1/projects/${projectId}/design-runs`, { method: "POST", json: {} });
}

export function getDesignRun(runId) {
  return request(`/api/v1/design-runs/${runId}`);
}

export function getDesignRunResult(runId) {
  return request(`/api/v1/design-runs/${runId}/result`);
}

export function fileUrl(runId, fileId) {
  return `${API_BASE}/api/v1/design-runs/${runId}/files/${fileId}`;
}

export function dwgUrl(runId) {
  return `${API_BASE}/api/v1/design-runs/${runId}/dwg`;
}

export async function fetchFileBlob(url) {
  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) {
    let body = null;
    try {
      body = await response.json();
    } catch {
      /* non-JSON */
    }
    const error = body && body.error ? body.error : {};
    throw new ApiError(response.status, error.code, error.message, error.details);
  }
  return response.blob();
}

export async function downloadFile(url, filename) {
  const blob = await fetchFileBlob(url);
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

// ── Presentation render ─────────────────────────────────────────────────

export function getPresentationRender(runId) {
  return request(`/api/v1/design-runs/${runId}/presentation-render`);
}

export function requestPresentationRender(runId) {
  return request(`/api/v1/design-runs/${runId}/presentation-render`, { method: "POST" });
}

export function presentationImageUrl(runId) {
  return `${API_BASE}/api/v1/design-runs/${runId}/presentation-render/image`;
}

// ── Share / pricing ─────────────────────────────────────────────────────

export function createShare(projectId) {
  return request(`/api/v1/projects/${projectId}/share`, { method: "POST" });
}

export function shareUrl(sharePath) {
  return `${API_BASE}${sharePath}`;
}

export function getPricing() {
  return request("/api/v1/pricing/current");
}

export { API_BASE };
