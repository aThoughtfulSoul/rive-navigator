/**
 * Rive UI Navigator - Sidebar Chat Interface
 * Handles user interaction, screenshot capture, agent communication,
 * task mode tracking, and dual-mode execution (Collaborative + Agentic).
 */

// ============ State ============
const state = {
  sessionId: `session_${Date.now()}`,
  pendingScreenshot: null,
  isLoading: false,
  messages: [],
  modelName: "gemini-3-flash-preview",
  assetGeneration: {
    active: false,
    loading: false,
    assetId: "",
    prompt: "",
    style: "sticker",
    previewDataUrl: "",
    revisedPrompt: "",
    sanitizedSvg: "",
  },
  // Task mode state (synced from backend)
  task: {
    active: false,
    name: "",
    currentStep: 0,
    totalSteps: 0,
    currentStepName: "",
  },
  // Dual mode: "collaborative" (user acts) vs "agentic" (agent acts)
  taskMode: "collaborative",
  // Agentic execution state
  executing: false,
  executionPaused: false,
  actionCount: 0,
  MAX_ACTIONS: 150,
  // Stuck detection
  lastActionLabel: "",
  repeatCount: 0,
  MAX_REPEATS: 2,
  actionFamilyHistory: [],
  MAX_ACTION_FAMILY_HISTORY: 6,
  invalidActionRecoveries: 0,
  MAX_INVALID_ACTION_RECOVERIES: 2,
  // Audio narration
  currentAudio: null,
};
const TASK_MODE_STORAGE_KEY = "rive-nav-task-mode";
const MODEL_STORAGE_KEY = "rive-nav-model";
const FLASH_MODEL_NAME = "gemini-3-flash-preview";
const PRO_MODEL_NAME = "gemini-3.1-pro-preview";
const DEFAULT_AGENT_API_URL = "http://localhost:8000";
const ASSET_PREVIEW_TIMEOUT_MS = 90000;

// ============ DOM Elements ============
const chatContainer = document.getElementById("chatContainer");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const captureBtn = document.getElementById("captureBtn");
const screenshotPreview = document.getElementById("screenshotPreview");
const previewImage = document.getElementById("previewImage");
const closePreview = document.getElementById("closePreview");
const proModel = document.getElementById("proModel");
const audioNarration = document.getElementById("audioNarration");
const micBtn = document.getElementById("micBtn");
const connectionStatus = document.getElementById("connectionStatus");
const assetPanel = document.getElementById("assetPanel");
const assetBtn = document.getElementById("assetBtn");
const assetCloseBtn = document.getElementById("assetCloseBtn");
const assetPromptInput = document.getElementById("assetPromptInput");
const assetStyleSelect = document.getElementById("assetStyleSelect");
const assetGenerateBtn = document.getElementById("assetGenerateBtn");
const assetStatus = document.getElementById("assetStatus");
const assetPreview = document.getElementById("assetPreview");
const assetPreviewImage = document.getElementById("assetPreviewImage");
const assetRegenerateBtn = document.getElementById("assetRegenerateBtn");
const assetUseBtn = document.getElementById("assetUseBtn");

// Task bar elements
const taskBar = document.getElementById("taskBar");
const taskName = document.getElementById("taskName");
const taskProgressFill = document.getElementById("taskProgressFill");
const taskProgressText = document.getElementById("taskProgressText");
const taskCurrentStep = document.getElementById("taskCurrentStep");
const taskEndBtn = document.getElementById("taskEndBtn");
const taskBackBtn = document.getElementById("taskBackBtn");
const taskDoneBtn = document.getElementById("taskDoneBtn");
const taskSkipBtn = document.getElementById("taskSkipBtn");

// Mode toggle elements
const modeToggle = document.getElementById("modeToggle");
const modeLabel = document.getElementById("modeLabel");

// Execution status elements
const executionStatus = document.getElementById("executionStatus");
const executionText = document.getElementById("executionText");
const pauseBtn = document.getElementById("pauseBtn");

// ============ Event Listeners ============

sendBtn.addEventListener("click", handleSend);

messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
});

messageInput.addEventListener("input", () => {
  messageInput.style.height = "auto";
  messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + "px";
});

captureBtn.addEventListener("click", handleCapture);
micBtn.addEventListener("click", toggleVoiceInput);

closePreview.addEventListener("click", () => {
  state.pendingScreenshot = null;
  screenshotPreview.style.display = "none";
});

document.querySelectorAll(".quick-action").forEach((btn) => {
  btn.addEventListener("click", () => {
    messageInput.value = btn.dataset.prompt;
    messageInput.focus();
    handleSend();
  });
});

if (proModel) {
  proModel.addEventListener("change", () => {
    syncModelFromUI();
    localStorage.setItem(MODEL_STORAGE_KEY, state.modelName);
    console.log(`[Sidebar] Model switched to: ${state.modelName}`);
  });
}

if (assetBtn) {
  assetBtn.addEventListener("click", () => {
    if (state.assetGeneration.active) {
      closeAssetPanel({ reset: false });
    } else {
      openAssetPanel();
    }
  });
}

if (assetCloseBtn) {
  assetCloseBtn.addEventListener("click", () => closeAssetPanel({ reset: false }));
}

if (assetGenerateBtn) {
  assetGenerateBtn.addEventListener("click", () => handleAssetPreviewRequest());
}

if (assetRegenerateBtn) {
  assetRegenerateBtn.addEventListener("click", () => handleAssetPreviewRequest());
}

if (assetUseBtn) {
  assetUseBtn.addEventListener("click", () => handleAssetImport());
}

if (assetPromptInput) {
  assetPromptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleAssetPreviewRequest();
    }
  });
}

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.shiftKey && e.key === "S") {
    e.preventDefault();
    handleCapture();
  }

  if (e.code === "Space" && e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
    e.preventDefault();
    startSidebarPushToTalk();
  }
});

document.addEventListener("keyup", (e) => {
  if (sidebarPushToTalkActive && (e.code === "Space" || e.key === "Control")) {
    e.preventDefault();
    stopSidebarPushToTalk();
  }
});

window.addEventListener("blur", () => {
  stopSidebarPushToTalk();
});

// Task control buttons
taskEndBtn.addEventListener("click", () => {
  state.executionPaused = true; // Stop agentic loop if running
  messageInput.value = "End this task, I want to go back to ask mode.";
  handleSend();
});

taskBackBtn.addEventListener("click", () => {
  messageInput.value = "Go back to the previous step.";
  handleSend();
});

taskDoneBtn.addEventListener("click", () => {
  messageInput.value = "I'm done with this step.";
  handleSend();
});

taskSkipBtn.addEventListener("click", () => {
  messageInput.value = "Skip this step and move to the next one.";
  handleSend();
});

// Mode toggle
modeToggle.addEventListener("change", () => {
  syncTaskModeFromUI();
  localStorage.setItem(TASK_MODE_STORAGE_KEY, state.taskMode);
  updateModeUI();

  if (state.taskMode === "collaborative") {
    // Switching to collaborative: stop any running agentic loop
    state.executionPaused = true;
    state.executing = false;
    updateExecutionStatus(null);
    // Stop any playing narration
    stopNarration();
  } else if (state.taskMode === "agentic" && state.task.active) {
    // Switching to agentic mid-task: kick off the agentic loop
    state.executionPaused = false;
    state.actionCount = 0;
    addMessage("agent", "Switching to Agentic mode — I'll take it from here!");
    resumeAgenticLoop();
  }

  console.log(`[Sidebar] Mode switched to: ${state.taskMode}`);
});

// Pause/Resume button
pauseBtn.addEventListener("click", () => {
  if (state.executionPaused) {
    // Resume
    state.executionPaused = false;
    pauseBtn.textContent = "Pause";
    // Trigger continuation by sending a screenshot to the agent
    resumeAgenticLoop();
  } else {
    // Pause
    state.executionPaused = true;
    pauseBtn.textContent = "Resume";
    updateExecutionStatus("Paused — click Resume to continue");
  }
});

// ============ Core Functions ============

/**
 * Handles sending a message to the agent.
 */
async function handleSend() {
  const text = messageInput.value.trim();
  if (!text || state.isLoading) return;

  if (!state.pendingScreenshot) {
    await handleCapture();
  }

  messageInput.value = "";
  messageInput.style.height = "auto";

  const welcome = chatContainer.querySelector(".welcome-message");
  if (welcome) welcome.remove();

  addMessage("user", text, state.pendingScreenshot);

  const screenshot = state.pendingScreenshot;
  state.pendingScreenshot = null;
  screenshotPreview.style.display = "none";

  setLoading(true);

  try {
    const result = await sendToAgent(text, screenshot);

    if (result.task_state) {
      updateTaskBar(result.task_state);
    }

    addMessage("agent", result.response || result.text || "No response.");

    // Non-blocking TTS narration (fire and forget)
    narrate(result.response || result.text || "");

    if (await maybeContinueAgenticLoop(result)) {
      return;
    }

    if (result.cursor_target) {
      // Collaborative mode: show visual cursor
      showAgentCursor(result.cursor_target);
    }
  } catch (error) {
    addMessage("agent", `Error: ${error.message}. Make sure the agent backend is running.`);
    updateConnectionStatus("error");
  } finally {
    setLoading(false);
  }
}

/**
 * Captures a screenshot of the active Rive tab.
 */
async function handleCapture() {
  try {
    const response = await chrome.runtime.sendMessage({
      type: "CAPTURE_SCREENSHOT",
    });

    if (response.error) {
      console.error("Capture failed:", response.error);
      return;
    }

    state.pendingScreenshot = response.screenshot;
    previewImage.src = response.screenshot;
    screenshotPreview.style.display = "block";
  } catch (error) {
    console.error("Screenshot capture error:", error);
  }
}

/**
 * Captures a screenshot silently (no preview) and returns the data URL.
 */
async function captureScreenshotSilent() {
  try {
    const response = await chrome.runtime.sendMessage({
      type: "CAPTURE_SCREENSHOT",
    });
    return response.error ? null : response.screenshot;
  } catch (error) {
    console.error("Silent capture error:", error);
    return null;
  }
}

/**
 * Sends message + screenshot to the ADK agent backend.
 */
async function sendToAgent(message, screenshot) {
  try {
    syncTaskModeFromUI();
    syncModelFromUI();
    const response = await chrome.runtime.sendMessage({
      type: "SEND_TO_AGENT",
      payload: {
        userMessage: message,
        screenshot: screenshot,
        domContext: null,
        sessionId: state.sessionId,
        taskMode: state.taskMode,
        model: state.modelName,
      },
    });

    if (response.error) {
      throw new Error(response.error);
    }

    updateConnectionStatus("connected");
    return response.agentResponse || { response: "No response from agent." };
  } catch (error) {
    return await sendToAgentDirect(message, screenshot);
  }
}

/**
 * Direct API call fallback.
 */
async function sendToAgentDirect(message, screenshot) {
  syncTaskModeFromUI();
  syncModelFromUI();
  const agentApiUrl = await getAgentApiUrl();

  const response = await fetchWithTimeout(
    `${agentApiUrl}/api/chat`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: message,
        screenshot: screenshot,
        dom_context: null,
        session_id: state.sessionId,
        user_id: "extension_user",
        task_mode: state.taskMode,
        model: state.modelName,
      }),
    },
    120000 // 2-minute timeout for LLM + screenshot processing
  );

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  const data = await response.json();
  updateConnectionStatus("connected");
  return data;
}

async function handleAssetPreviewRequest() {
  if (state.assetGeneration.loading) return;

  const prompt = assetPromptInput ? assetPromptInput.value.trim() : "";
  if (!prompt) {
    setAssetStatus("Describe the asset you want to generate first.", "error");
    return;
  }

  state.assetGeneration.prompt = prompt;
  state.assetGeneration.style = assetStyleSelect ? assetStyleSelect.value : "sticker";
  setAssetBusy(true, "Generating preview with Gemini image generation...");

  try {
    const agentApiUrl = await getAgentApiUrl();
    const response = await fetchWithTimeout(
      `${agentApiUrl}/api/assets/preview`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: state.assetGeneration.prompt,
          style: state.assetGeneration.style,
        }),
      },
      ASSET_PREVIEW_TIMEOUT_MS
    );

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || `Preview generation failed with ${response.status}`);
    }

    state.assetGeneration.assetId = data.asset_id || "";
    state.assetGeneration.previewDataUrl = data.preview_data_url || "";
    state.assetGeneration.revisedPrompt = data.revised_prompt || state.assetGeneration.prompt;
    state.assetGeneration.sanitizedSvg = "";

    if (!state.assetGeneration.previewDataUrl) {
      throw new Error("The preview response did not include an image.");
    }

    if (assetPreviewImage) {
      assetPreviewImage.src = state.assetGeneration.previewDataUrl;
    }
    if (assetPreview) {
      assetPreview.style.display = "block";
    }

    setAssetStatus(
      "Preview ready. If it looks right, use it and I’ll trace an SVG, sanitize it, and paste it into Rive.",
      "success"
    );
  } catch (error) {
    console.error("[Sidebar] Asset preview generation failed:", error);
    setAssetStatus(`Preview failed: ${error.message}`, "error");
  } finally {
    setAssetBusy(false);
  }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function handleAssetImport() {
  if (state.assetGeneration.loading || !state.assetGeneration.assetId) return;

  setAssetBusy(true, "Tracing SVG and preparing clipboard paste...");

  try {
    const agentApiUrl = await getAgentApiUrl();
    const response = await fetch(`${agentApiUrl}/api/assets/vectorize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_id: state.assetGeneration.assetId,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || `SVG conversion failed with ${response.status}`);
    }

    const sanitizedSvg = data.sanitized_svg || "";
    if (!sanitizedSvg) {
      throw new Error("The vectorizer did not return SVG data.");
    }

    state.assetGeneration.sanitizedSvg = sanitizedSvg;
    await writeSvgToClipboard(sanitizedSvg);

    const pasteResult = await chrome.runtime.sendMessage({
      type: "IMPORT_SVG_VIA_PASTE",
      svgLength: sanitizedSvg.length,
    });
    if (!pasteResult || !pasteResult.success) {
      throw new Error(pasteResult?.error || "Clipboard paste into Rive failed.");
    }

    await sleep(1200);
    const screenshot = await captureScreenshotSilent();
    if (screenshot) {
      state.pendingScreenshot = screenshot;
      previewImage.src = screenshot;
      screenshotPreview.style.display = "block";
    }

    const pathCount = data.stats?.path_count;
    addMessage(
      "agent",
      `The asset was pasted into Rive${pathCount ? ` (${pathCount} paths)` : ""}. I captured the current editor state, so you can ask me to animate it next.`
    );

    closeAssetPanel({ reset: true });
    messageInput.focus();
  } catch (error) {
    console.error("[Sidebar] Asset import failed:", error);
    setAssetStatus(`Import failed: ${error.message}`, "error");
  } finally {
    setAssetBusy(false);
  }
}

async function writeSvgToClipboard(svgText) {
  if (!svgText) {
    throw new Error("No SVG data available to copy.");
  }

  if (navigator.clipboard?.write && typeof ClipboardItem !== "undefined") {
    try {
      const clipboardItem = new ClipboardItem({
        "text/plain": new Blob([svgText], { type: "text/plain" }),
        "text/html": new Blob([svgText], { type: "text/html" }),
        "image/svg+xml": new Blob([svgText], { type: "image/svg+xml" }),
      });
      await navigator.clipboard.write([clipboardItem]);
      return;
    } catch (error) {
      console.warn("[Sidebar] Rich SVG clipboard write failed, falling back to text/plain:", error);
    }
  }

  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(svgText);
    return;
  }

  throw new Error("Clipboard write is not available in this browser context.");
}

function openAssetPanel() {
  state.assetGeneration.active = true;
  if (assetPanel) {
    assetPanel.style.display = "block";
  }
  if (assetBtn) {
    assetBtn.classList.add("active");
  }
  if (assetPromptInput) {
    assetPromptInput.focus();
    assetPromptInput.setSelectionRange(assetPromptInput.value.length, assetPromptInput.value.length);
  }
}

function closeAssetPanel({ reset = false } = {}) {
  state.assetGeneration.active = false;
  if (assetPanel) {
    assetPanel.style.display = "none";
  }
  if (assetBtn) {
    assetBtn.classList.remove("active");
  }
  if (reset) {
    resetAssetState();
  }
}

function resetAssetState() {
  state.assetGeneration = {
    active: false,
    loading: false,
    assetId: "",
    prompt: "",
    style: assetStyleSelect ? assetStyleSelect.value : "sticker",
    previewDataUrl: "",
    revisedPrompt: "",
    sanitizedSvg: "",
  };

  if (assetPromptInput) {
    assetPromptInput.value = "";
    assetPromptInput.style.height = "auto";
  }
  if (assetPreview) {
    assetPreview.style.display = "none";
  }
  if (assetPreviewImage) {
    assetPreviewImage.removeAttribute("src");
  }
  setAssetStatus("", "idle");
}

function setAssetBusy(isBusy, statusText = "") {
  state.assetGeneration.loading = isBusy;

  if (assetGenerateBtn) assetGenerateBtn.disabled = isBusy;
  if (assetRegenerateBtn) assetRegenerateBtn.disabled = isBusy;
  if (assetUseBtn) assetUseBtn.disabled = isBusy || !state.assetGeneration.assetId;
  if (assetPromptInput) assetPromptInput.disabled = isBusy;
  if (assetStyleSelect) assetStyleSelect.disabled = isBusy;

  if (statusText) {
    setAssetStatus(statusText, isBusy ? "loading" : "success");
  }
}

function setAssetStatus(text, tone = "idle") {
  if (!assetStatus) return;

  assetStatus.textContent = text || "";
  assetStatus.dataset.tone = tone;
  assetStatus.style.display = text ? "block" : "none";
}

function normalizeAgentApiUrl(url) {
  return String(url || DEFAULT_AGENT_API_URL).trim().replace(/\/+$/, "");
}

function getAgentApiUrl() {
  return new Promise((resolve) => {
    if (!chrome?.storage?.sync) {
      resolve(DEFAULT_AGENT_API_URL);
      return;
    }

    chrome.storage.sync.get({ agentApiUrl: DEFAULT_AGENT_API_URL }, (result) => {
      resolve(normalizeAgentApiUrl(result.agentApiUrl));
    });
  });
}

// ============ Agentic Execution Loop ============

/**
 * Executes an agent action on the Rive canvas, then auto-loops.
 * Flow: execute action → wait → capture screenshot → send to agent → repeat
 */
async function executeAgentAction(action) {
  if (!action || !action.type) return;

  // Safety cap
  state.actionCount++;
  if (state.actionCount > state.MAX_ACTIONS) {
    addMessage("agent", `Safety limit reached (${state.MAX_ACTIONS} actions). Pausing execution.`);
    state.executionPaused = true;
    state.executing = false;
    updateExecutionStatus(null);
    return;
  }

  if (isSemanticActionLoop(action)) {
    console.warn(`[Sidebar] Semantic loop detected for action family: ${getActionFamily(action)}`);
    state.actionFamilyHistory = [];
    state.lastActionLabel = "";
    state.repeatCount = 0;
    setLoading(true);
    const screenshot = await captureScreenshotSilent();
    let stuckMsg =
      `[STUCK: The recent actions are looping around the same problem without changing the screenshot. ` +
      `Stop cycling between selection clicks, opacity fields, or edit-mode controls. Reassess what is blocking this step.]`;
    if (getActionFamily(action) === "opacity") {
      stuckMsg +=
        " Do not keep switching between layer opacity and fill opacity. Verify the correct object is selected, exit any active edit mode or blocking dialog, then make one targeted opacity change.";
    }
    const result = await sendToAgent(stuckMsg, screenshot);
    setLoading(false);
    if (result.task_state) updateTaskBar(result.task_state);
    addMessage("agent", result.response || "Trying a different approach...");
    narrate(result.response || "");
    if (await maybeContinueAgenticLoop(result)) {
      return;
    } else {
      state.executing = false;
      updateExecutionStatus(null);
    }
    return;
  }

  // Stuck detection: if same action repeats, tell agent to try differently
  const actionKey = buildActionKey(action);
  if (actionKey === state.lastActionLabel) {
    state.repeatCount++;
    if (state.repeatCount >= state.MAX_REPEATS) {
      console.warn(`[Sidebar] Stuck detected: "${action.label}" repeated ${state.repeatCount} times`);
      // Don't execute — send a "stuck" message instead
      state.repeatCount = 0;
      state.lastActionLabel = "";
      setLoading(true);
      const screenshot = await captureScreenshotSilent();
      let stuckMsg =
        `[STUCK: The action "${action.label}" has been attempted ${state.MAX_REPEATS} times without success. ` +
        `The click target is likely wrong. Try a DIFFERENT approach — use a keyboard shortcut instead of clicking, ` +
        `or click a different location. Do NOT repeat the same action.]`;
      if (isSelectionLikeAction(action)) {
        stuckMsg +=
          " If hierarchy selection is ambiguous, click the visible object on the stage/canvas instead and verify that handles or Inspector properties changed before continuing.";
      }
      const result = await sendToAgent(stuckMsg, screenshot);
      setLoading(false);
      if (result.task_state) updateTaskBar(result.task_state);
      addMessage("agent", result.response || "Trying a different approach...");
      narrate(result.response || "");
      if (await maybeContinueAgenticLoop(result)) {
        return;
      } else {
        state.executing = false;
        updateExecutionStatus(null);
      }
      return;
    }
  } else {
    state.lastActionLabel = actionKey;
    state.repeatCount = 0;
  }

  recordActionFamily(action);

  state.executing = true;
  updateExecutionStatus(`Executing: ${action.label || action.type}...`);

  try {
    // Send action to content script for execution
    const result = await chrome.runtime.sendMessage({
      type: "EXECUTE_ACTION",
      action: action,
    });

    console.log(`[Sidebar] Action result:`, result);

    if (!result.success) {
      console.warn(`[Sidebar] Action failed:`, result.error);
      addMessage("agent", `Action failed: ${result.error}. Trying to continue...`);
    }

    // Wait for Rive UI to settle
    await sleep(800);

    // Check if paused or task ended
    if (state.executionPaused || !state.task.active) {
      state.executing = false;
      updateExecutionStatus(state.executionPaused ? "Paused" : null);
      return;
    }

    // Auto-capture screenshot for verification
    updateExecutionStatus("Capturing result...");
    const screenshot = await captureScreenshotSilent();

    if (!screenshot) {
      addMessage("agent", "Could not capture screenshot for verification.");
      state.executing = false;
      updateExecutionStatus(null);
      return;
    }

    // Re-check pause before spending an LLM call on verification
    if (state.executionPaused || !state.task.active) {
      state.executing = false;
      updateExecutionStatus(state.executionPaused ? "Paused" : null);
      return;
    }

    // Send verification message to agent with screenshot
    updateExecutionStatus("Agent analyzing...");
    setLoading(true);

    const verifyMessage =
      `[Executed: ${action.label || action.type}] ` +
      `Examine the screenshot carefully. ` +
      `State whether the action succeeded or failed. ` +
      `If it failed or the UI did not change as expected, choose a DIFFERENT strategy. ` +
      `If it succeeded, proceed to the next step.`;
    const agentResult = await sendToAgent(verifyMessage, screenshot);

    setLoading(false);

    // Check pause again after the (potentially long) LLM call returns
    if (state.executionPaused || !state.task.active) {
      if (agentResult.task_state) {
        updateTaskBar(agentResult.task_state);
      }
      addMessage("agent", agentResult.response || "No response.");
      narrate(agentResult.response || "");
      state.executing = false;
      updateExecutionStatus(state.executionPaused ? "Paused" : null);
      return;
    }

    if (agentResult.task_state) {
      updateTaskBar(agentResult.task_state);
    }

    addMessage("agent", agentResult.response || "No response.");
    narrate(agentResult.response || "");

    // Check if task completed or paused
    if (!state.task.active || state.executionPaused) {
      state.executing = false;
      updateExecutionStatus(null);
      return;
    }

    if (await maybeContinueAgenticLoop(agentResult)) {
      return;
    } else {
      state.executing = false;
      updateExecutionStatus(null);
    }
  } catch (error) {
    console.error("[Sidebar] Agentic execution error:", error);
    addMessage("agent", `Execution error: ${error.message}`);
    state.executing = false;
    updateExecutionStatus(null);
  }
}

/**
 * Resumes the agentic loop after a pause.
 */
async function resumeAgenticLoop(
  resumeMessage = "[Resumed] Continue from where you left off. Here is the current state."
) {
  updateExecutionStatus("Resuming...");

  const screenshot = await captureScreenshotSilent();
  if (!screenshot) {
    updateExecutionStatus("Could not capture screenshot");
    return;
  }

  setLoading(true);

  try {
    const result = await sendToAgent(resumeMessage, screenshot);

    setLoading(false);

    if (result.task_state) {
      updateTaskBar(result.task_state);
    }

    addMessage("agent", result.response || "No response.");
    narrate(result.response || "");

    if (await maybeContinueAgenticLoop(result)) {
      return;
    } else {
      updateExecutionStatus(null);
    }
  } catch (error) {
    setLoading(false);
    addMessage("agent", `Resume error: ${error.message}`);
    updateExecutionStatus(null);
  }
}

// ============ Task Mode UI ============

function updateTaskBar(taskState) {
  if (!taskState) return;

  state.task = {
    active: taskState.active || false,
    name: taskState.name || "",
    currentStep: taskState.current_step || 0,
    totalSteps: taskState.total_steps || 0,
    currentStepName: taskState.current_step_name || "",
  };

  if (state.task.active) {
    taskBar.style.display = "block";
    taskName.textContent = state.task.name;
    taskProgressText.textContent = `Step ${state.task.currentStep}/${state.task.totalSteps}`;
    taskCurrentStep.textContent = state.task.currentStepName;

    const percent = ((state.task.currentStep - 1) / state.task.totalSteps) * 100;
    taskProgressFill.style.width = `${percent}%`;

    messageInput.placeholder =
      state.taskMode === "agentic"
        ? "Agent is working... type to intervene"
        : 'Say "done" when finished with this step...';

    taskBackBtn.disabled = state.task.currentStep <= 1;
    taskBackBtn.style.opacity = state.task.currentStep <= 1 ? "0.4" : "1";

    // Show/hide collaborative controls based on mode
    updateModeUI();

    // Reset action count on new task
    if (state.task.currentStep === 1) {
      state.actionCount = 0;
    }
  } else {
    taskBar.style.display = "none";
    messageInput.placeholder = "Ask about Rive...";
    state.executing = false;
    state.executionPaused = false;
    updateExecutionStatus(null);

    if (taskState.completed) {
      showTaskComplete(taskState.name, taskState.total_steps);
    }
  }
}

function showTaskComplete(taskNameText, totalSteps) {
  const celebrationEl = document.createElement("div");
  celebrationEl.className = "message agent";
  celebrationEl.innerHTML = `
    <div class="message-label">Rive Navigator</div>
    <div class="message-bubble" style="text-align: center; padding: 16px;">
      <div style="font-size: 24px; margin-bottom: 8px;">&#127881;</div>
      <strong>Task Complete!</strong><br>
      <span style="color: var(--text-secondary); font-size: 12px;">
        Finished "${taskNameText}" — all ${totalSteps} steps done!
      </span>
    </div>
  `;
  chatContainer.appendChild(celebrationEl);
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

/**
 * Updates UI elements based on current task mode.
 */
function updateModeUI() {
  const isAgentic = state.taskMode === "agentic";

  // Update mode label
  if (modeLabel) {
    modeLabel.textContent = isAgentic ? "Agentic" : "Collaborative";
    modeLabel.style.color = isAgentic ? "var(--success)" : "var(--accent)";
  }

  // Update toggle state (without triggering change event)
  if (modeToggle && modeToggle.checked !== isAgentic) {
    modeToggle.checked = isAgentic;
  }

  // Show/hide collaborative task controls
  const collabControls = document.getElementById("collabControls");
  if (collabControls) {
    collabControls.style.display = isAgentic ? "none" : "flex";
  }

  // Show/hide execution status bar
  if (executionStatus) {
    executionStatus.style.display =
      isAgentic && state.task.active ? "flex" : "none";
  }

  // Update connection status text
  if (state.task.active) {
    const statusText = connectionStatus.querySelector(".status-text");
    if (statusText) {
      statusText.textContent = isAgentic ? "Agentic Mode" : "Task Mode";
    }
  }
}

async function maybeContinueAgenticLoop(result) {
  if (state.taskMode !== "agentic" || state.executionPaused || !state.task.active) {
    state.invalidActionRecoveries = 0;
    return false;
  }

  if (result.action) {
    state.invalidActionRecoveries = 0;
    await executeAgentAction(result.action);
    return true;
  }

  if (!result.needs_retry) {
    state.invalidActionRecoveries = 0;
    return false;
  }

  state.invalidActionRecoveries++;

  const warningText = Array.isArray(result.warnings) && result.warnings.length
    ? result.warnings[result.warnings.length - 1]
    : "The previous action was rejected by validation.";

  if (state.invalidActionRecoveries > state.MAX_INVALID_ACTION_RECOVERIES) {
    addMessage(
      "agent",
      `I paused because the last actions were invalid and could not be executed. ${warningText}`
    );
    state.executionPaused = true;
    state.executing = false;
    updateExecutionStatus("Paused after invalid actions");
    return true;
  }

  updateExecutionStatus("Reassessing after invalid action...");
  await sleep(400);
  await resumeAgenticLoop(
    `[Recovery] The previous action was rejected by validation: ${warningText} Reassess the current screenshot and choose a different valid action.`
  );
  return true;
}

function syncTaskModeFromUI() {
  if (!modeToggle) return;
  state.taskMode = modeToggle.checked ? "agentic" : "collaborative";
}

function syncModelFromUI() {
  if (!proModel) return;
  state.modelName = proModel.checked ? PRO_MODEL_NAME : FLASH_MODEL_NAME;
}

function normalizeActionLabel(label) {
  return String(label || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .replace(/\bdouble-?click\b/g, "click")
    .trim();
}

function roundedCoord(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "";
  return Math.round(value / 4) * 4;
}

function buildActionKey(action) {
  const normalizedLabel = normalizeActionLabel(action.label);
  if (normalizedLabel) {
    return `${action.type}:${normalizedLabel}`;
  }

  if (action.type === "drag") {
    return [
      action.type,
      roundedCoord(action.x1),
      roundedCoord(action.y1),
      roundedCoord(action.x2),
      roundedCoord(action.y2),
    ].join(":");
  }

  return [
    action.type,
    roundedCoord(action.x),
    roundedCoord(action.y),
    action.text || "",
    action.key || "",
  ].join(":");
}

function isSelectionLikeAction(action) {
  const text = `${action.type} ${action.label || ""}`.toLowerCase();
  return /(select|selection|group|hierarchy|layer|object|svg)/.test(text);
}

function getActionFamily(action) {
  const text = `${action.type} ${action.label || ""} ${action.text || ""}`.toLowerCase();
  if (/opacity/.test(text)) return "opacity";
  if (/(select|selection|group|hierarchy|layer|object|ellipse|shadow)/.test(text)) return "selection";
  if (/(done editing|convert to custom path|path edit|editing)/.test(text)) return "edit-mode";
  if (action.type === "type") return "inspector-type";
  return action.type;
}

function recordActionFamily(action) {
  state.actionFamilyHistory.push(getActionFamily(action));
  if (state.actionFamilyHistory.length > state.MAX_ACTION_FAMILY_HISTORY) {
    state.actionFamilyHistory.shift();
  }
}

function isSemanticActionLoop(action) {
  const family = getActionFamily(action);
  const recent = state.actionFamilyHistory.slice(-4);

  if (family === "opacity") {
    const allowed = new Set(["opacity", "selection", "edit-mode", "inspector-type"]);
    return recent.length >= 3 && recent.every((entry) => allowed.has(entry));
  }

  if (family === "selection") {
    return recent.length >= 3 && recent.every((entry) => entry === "selection" || entry === "opacity");
  }

  return false;
}

function initializeTaskMode() {
  if (!modeToggle) return;

  const savedMode = localStorage.getItem(TASK_MODE_STORAGE_KEY);
  if (savedMode === "agentic" || savedMode === "collaborative") {
    modeToggle.checked = savedMode === "agentic";
  }

  syncTaskModeFromUI();
  updateModeUI();
}

function initializeModelPreference() {
  if (!proModel) return;

  const savedModel = localStorage.getItem(MODEL_STORAGE_KEY);
  if (savedModel === PRO_MODEL_NAME || savedModel === FLASH_MODEL_NAME) {
    proModel.checked = savedModel === PRO_MODEL_NAME;
  } else {
    proModel.checked = false;
  }

  syncModelFromUI();
}

/**
 * Updates the execution status bar text.
 */
function updateExecutionStatus(text) {
  if (!executionStatus || !executionText) return;

  if (text) {
    executionStatus.style.display = "flex";
    executionText.textContent = text;
  } else {
    if (state.taskMode !== "agentic" || !state.task.active) {
      executionStatus.style.display = "none";
    } else {
      executionText.textContent = "Ready";
    }
  }
}

// ============ UI Functions ============

function addMessage(role, text, screenshotUrl = null) {
  const messageEl = document.createElement("div");
  messageEl.className = `message ${role}`;

  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : "Rive Navigator";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";

  if (role === "agent") {
    bubble.innerHTML = formatAgentResponse(text);
  } else {
    bubble.textContent = text;
  }

  if (screenshotUrl) {
    const img = document.createElement("img");
    img.className = "message-screenshot";
    img.src = screenshotUrl;
    img.alt = "Screenshot";
    img.addEventListener("click", () => {
      const w = window.open();
      w.document.write(`<img src="${screenshotUrl}" style="max-width:100%">`);
    });
    bubble.appendChild(img);
  }

  messageEl.appendChild(label);
  messageEl.appendChild(bubble);
  chatContainer.appendChild(messageEl);
  chatContainer.scrollTop = chatContainer.scrollHeight;

  state.messages.push({ role, text, timestamp: Date.now() });
}

function formatAgentResponse(text) {
  if (!text) return "";

  return text
    .replace(/```(\w*)\n?([\s\S]*?)```/g, "<pre><code>$2</code></pre>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/^\d+\.\s+(.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/s, "<ol>$1</ol>")
    .replace(/\n/g, "<br>");
}

function setLoading(loading) {
  state.isLoading = loading;
  sendBtn.disabled = loading;

  const existing = chatContainer.querySelector(".loading-dots");
  if (existing) existing.remove();

  if (loading) {
    const loader = document.createElement("div");
    loader.className = "loading-dots";
    loader.innerHTML = "<span></span><span></span><span></span>";
    chatContainer.appendChild(loader);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    updateConnectionStatus("loading");
  }
}

function updateConnectionStatus(status) {
  const dot = connectionStatus.querySelector(".status-dot");
  const text = connectionStatus.querySelector(".status-text");

  dot.className = "status-dot";

  switch (status) {
    case "connected":
      text.textContent = state.task.active
        ? state.taskMode === "agentic"
          ? "Agentic Mode"
          : "Task Mode"
        : "Connected";
      break;
    case "loading":
      dot.classList.add("loading");
      text.textContent = state.executing ? "Executing..." : "Thinking...";
      break;
    case "error":
      dot.classList.add("disconnected");
      text.textContent = "Disconnected";
      break;
    default:
      text.textContent = "Ready";
  }
}

// ============ Agent Cursor (Collaborative Mode) ============

async function showAgentCursor(cursorTarget) {
  if (!cursorTarget || !cursorTarget.x || !cursorTarget.y) return;

  try {
    await chrome.runtime.sendMessage({
      type: "SHOW_CURSOR",
      x: cursorTarget.x,
      y: cursorTarget.y,
      label: cursorTarget.label || "",
    });
  } catch (error) {
    console.warn("[Sidebar] Could not send cursor:", error);
  }
}

async function hideAgentCursor() {
  try {
    await chrome.runtime.sendMessage({ type: "HIDE_CURSOR" });
  } catch (error) {
    // Silently ignore
  }
}

// ============ Voice Input (STT) ============

let isRecording = false;
let sidebarPushToTalkActive = false;

initializeModelPreference();
initializeTaskMode();

async function startSidebarPushToTalk() {
  if (sidebarPushToTalkActive || isRecording) return;

  sidebarPushToTalkActive = true;
  isRecording = true;
  micBtn.classList.add("recording");
  messageInput.placeholder = "Listening (Ctrl+Space)...";
  messageInput.value = "";

  try {
    const response = await chrome.runtime.sendMessage({
      type: "START_VOICE_INPUT",
      options: { continuous: true, pushToTalk: true },
    });

    if (response?.error) {
      sidebarPushToTalkActive = false;
      isRecording = false;
      micBtn.classList.remove("recording");
      messageInput.placeholder = "Ask about Rive...";
      addMessage("agent", response.error);
    }
  } catch (err) {
    sidebarPushToTalkActive = false;
    isRecording = false;
    micBtn.classList.remove("recording");
    messageInput.placeholder = "Ask about Rive...";
    addMessage("agent", "Could not start push-to-talk. Make sure you're on a Rive editor page.");
  }
}

function stopSidebarPushToTalk() {
  if (!sidebarPushToTalkActive) return;

  sidebarPushToTalkActive = false;
  chrome.runtime.sendMessage({ type: "STOP_VOICE_INPUT" });
}

/**
 * Toggles voice input on/off.
 *
 * Speech recognition runs in the CONTENT SCRIPT (on the Rive page) because
 * Chrome extension sidepanels (chrome-extension:// origin) cannot access
 * the microphone. The content script runs on https://rive.app which has
 * normal web permissions including mic access.
 *
 * Flow: sidebar → background relay → content script (runs SpeechRecognition)
 *       content script → chrome.runtime.sendMessage → sidebar receives results
 */
async function toggleVoiceInput() {
  if (isRecording) {
    // Stop recording
    chrome.runtime.sendMessage({ type: "STOP_VOICE_INPUT" });
    isRecording = false;
    micBtn.classList.remove("recording");
    messageInput.placeholder = "Ask about Rive...";
    return;
  }

  // Start recording via content script
  isRecording = true;
  micBtn.classList.add("recording");
  messageInput.placeholder = "Listening...";
  messageInput.value = "";

  try {
    const response = await chrome.runtime.sendMessage({ type: "START_VOICE_INPUT" });
    if (response?.error) {
      isRecording = false;
      micBtn.classList.remove("recording");
      messageInput.placeholder = "Ask about Rive...";
      addMessage("agent", response.error);
    }
  } catch (err) {
    isRecording = false;
    micBtn.classList.remove("recording");
    messageInput.placeholder = "Ask about Rive...";
    addMessage("agent", "Could not start voice input. Make sure you're on a Rive editor page.");
  }
}

// Listen for voice results relayed from the content script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Ctrl+Space from the Rive page — pause/resume agentic loop if running,
  // otherwise fall through to let the content script start push-to-talk.
  if (message.type === "CTRL_SPACE") {
    if (state.taskMode === "agentic" && state.executing) {
      if (state.executionPaused) {
        state.executionPaused = false;
        pauseBtn.textContent = "Pause";
        resumeAgenticLoop();
      } else {
        state.executionPaused = true;
        pauseBtn.textContent = "Resume";
        updateExecutionStatus("Paused — Ctrl+Space or click Resume to continue");
      }
      sendResponse({ agentPaused: state.executionPaused });
      return;
    }
    // Not in agentic execution — let content script handle as push-to-talk
    sendResponse({});
    return;
  }

  // Push-to-talk started from the Rive page via Ctrl+Space
  if (message.type === "PUSH_TO_TALK_START") {
    isRecording = true;
    micBtn.classList.add("recording");
    messageInput.placeholder = "Listening (Ctrl+Space)...";
    messageInput.value = "";
  }

  if (message.type === "VOICE_RESULT" && isRecording) {
    // Only update input if there's actual transcript text (skip empty onend signal)
    if (message.transcript) {
      messageInput.value = message.transcript;
      messageInput.style.height = "auto";
      messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + "px";
    }

    if (message.isFinal) {
      // Set isRecording false FIRST — prevents the duplicate onend signal
      // from triggering a second handleSend()
      sidebarPushToTalkActive = false;
      isRecording = false;
      micBtn.classList.remove("recording");
      messageInput.placeholder = "Ask about Rive...";

      // Auto-send if we got text
      const currentText = messageInput.value.trim();
      if (currentText) {
        handleSend();
      }
    }
  }

  if (message.type === "VOICE_ERROR") {
    sidebarPushToTalkActive = false;
    isRecording = false;
    micBtn.classList.remove("recording");
    messageInput.placeholder = "Ask about Rive...";
    if (message.error) {
      addMessage("agent", message.error);
    }
  }
});

// ============ Audio Narration ============

/**
 * Narrates the agent's response text via Gemini TTS.
 * Non-blocking: fires and forgets. Does not delay the agentic loop.
 * Shows subtitle overlay on the Rive page while audio plays.
 *
 * Uses sentence pipelining for low latency:
 *  1. Split text into sentences
 *  2. Fire TTS for sentence 1 immediately (short text = fast generation)
 *  3. Start playing sentence 1 as soon as it returns
 *  4. While sentence 1 plays, pre-fetch sentence 2's audio
 *  5. When sentence 1 ends, sentence 2 is ready — play immediately
 *  6. Repeat until all sentences are spoken
 */

// Unique ID incremented per narrate() call so stale pipelines can self-cancel
let narrateGeneration = 0;

async function narrate(text) {
  if (!audioNarration || !audioNarration.checked || !text) return;

  // Strip markdown formatting for cleaner speech
  const cleanText = text
    .replace(/```[\s\S]*?```/g, "")     // Remove code blocks
    .replace(/`[^`]+`/g, "")            // Remove inline code
    .replace(/\*\*(.+?)\*\*/g, "$1")    // Bold → plain
    .replace(/\*(.+?)\*/g, "$1")        // Italic → plain
    .replace(/^\d+\.\s+/gm, "")         // Remove list numbers
    .replace(/<[^>]+>/g, "")            // Remove HTML tags
    .replace(/\n+/g, " ")              // Newlines → spaces
    .trim();

  if (!cleanText || cleanText.length < 5) return;

  // Cancel any in-progress narration
  stopNarration();

  const generation = ++narrateGeneration;
  const agentApiUrl = await getAgentApiUrl();

  // Split into sentences (keep the delimiter attached)
  const sentences = cleanText.match(/[^.!?]+[.!?]+(?:\s|$)|[^.!?]+$/g) || [cleanText];
  const trimmed = sentences.map(s => s.trim()).filter(s => s.length > 0);
  if (trimmed.length === 0) return;

  // Show full text as subtitle
  showSubtitle(cleanText);

  /**
   * Fetches TTS audio for a single sentence. Returns an Audio object or null.
   */
  async function fetchAudio(sentence) {
    try {
      const res = await fetch(`${agentApiUrl}/api/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: sentence }),
      });
      if (!res.ok) {
        let detail = "";
        try {
          const errorData = await res.json();
          detail = errorData?.detail || "";
        } catch {
          detail = "";
        }
        console.warn(`[Sidebar] TTS sentence fetch failed (${res.status})${detail ? `: ${detail}` : ""}`);
        return null;
      }
      const data = await res.json();
      return new Audio(`data:audio/wav;base64,${data.audio_base64}`);
    } catch {
      return null;
    }
  }

  /**
   * Plays an Audio object and returns a promise that resolves when it ends.
   */
  function playAudio(audio) {
    return new Promise((resolve) => {
      audio.addEventListener("ended", resolve, { once: true });
      audio.addEventListener("error", resolve, { once: true });
      audio.play().catch(resolve);
    });
  }

  try {
    // Kick off the first sentence fetch immediately
    let nextAudioPromise = fetchAudio(trimmed[0]);

    for (let i = 0; i < trimmed.length; i++) {
      // Check if this narration was cancelled
      if (narrateGeneration !== generation) return;

      // Wait for the current sentence's audio
      const audio = await nextAudioPromise;

      // Start pre-fetching the NEXT sentence while this one plays
      if (i + 1 < trimmed.length) {
        nextAudioPromise = fetchAudio(trimmed[i + 1]);
      }

      if (!audio || narrateGeneration !== generation) continue;

      // Play current sentence
      state.currentAudio = audio;
      await playAudio(audio);
      state.currentAudio = null;
    }
  } catch (error) {
    console.warn("[Sidebar] TTS narration failed:", error.message);
  } finally {
    if (narrateGeneration === generation) {
      state.currentAudio = null;
      hideSubtitle();
    }
  }
}

/**
 * Stops any in-progress narration pipeline.
 */
function stopNarration() {
  narrateGeneration++;
  if (state.currentAudio) {
    state.currentAudio.pause();
    state.currentAudio = null;
  }
  hideSubtitle();
}

/**
 * Sends subtitle text to the content script for overlay on the Rive page.
 */
async function showSubtitle(text) {
  try {
    await chrome.runtime.sendMessage({
      type: "SHOW_SUBTITLE",
      text: text,
    });
  } catch (error) {
    console.warn("[Sidebar] Could not send subtitle:", error);
  }
}

/**
 * Hides the subtitle overlay on the Rive page.
 */
async function hideSubtitle() {
  try {
    await chrome.runtime.sendMessage({ type: "HIDE_SUBTITLE" });
  } catch (error) {
    // Silently ignore
  }
}

// ============ Utilities ============

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
