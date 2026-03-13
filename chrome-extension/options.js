const DEFAULT_AGENT_API_URL = "http://localhost:8000";
const STORAGE_KEY = "agentApiUrl";

const agentApiUrlInput = document.getElementById("agentApiUrl");
const saveBtn = document.getElementById("saveBtn");
const resetBtn = document.getElementById("resetBtn");
const statusEl = document.getElementById("status");

function normalizeApiUrl(value) {
  const trimmed = (value || "").trim();
  return trimmed.replace(/\/+$/, "");
}

function readStoredApiUrl() {
  return new Promise((resolve) => {
    chrome.storage.sync.get({ [STORAGE_KEY]: DEFAULT_AGENT_API_URL }, (result) => {
      resolve(normalizeApiUrl(result[STORAGE_KEY] || DEFAULT_AGENT_API_URL));
    });
  });
}

function writeStoredApiUrl(value) {
  return new Promise((resolve) => {
    chrome.storage.sync.set({ [STORAGE_KEY]: value }, resolve);
  });
}

function setStatus(message) {
  statusEl.textContent = message;
}

async function loadOptions() {
  const apiUrl = await readStoredApiUrl();
  agentApiUrlInput.value = apiUrl;
}

async function saveOptions() {
  const normalized = normalizeApiUrl(agentApiUrlInput.value) || DEFAULT_AGENT_API_URL;
  await writeStoredApiUrl(normalized);
  agentApiUrlInput.value = normalized;
  setStatus(`Saved backend URL: ${normalized}`);
}

async function resetOptions() {
  await writeStoredApiUrl(DEFAULT_AGENT_API_URL);
  agentApiUrlInput.value = DEFAULT_AGENT_API_URL;
  setStatus("Reset backend URL to localhost.");
}

saveBtn.addEventListener("click", saveOptions);
resetBtn.addEventListener("click", resetOptions);

loadOptions();
