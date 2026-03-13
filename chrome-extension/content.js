/**
 * Rive UI Navigator - Content Script
 * Runs on rive.app pages.
 *
 * Responsibility: Visual cursor overlay for collaborative and agentic mode feedback.
 * Action execution is handled by background.js via CDP (Chrome DevTools Protocol)
 * because Flutter Web ignores synthetic JavaScript events (isTrusted: false).
 */

// ============ Cursor Overlay State ============

let cursorOverlay = null;
let cursorLabel = null;
let cursorRing = null;
let hideTimeout = null;

// ============ Subtitle Overlay State ============

let subtitleOverlay = null;
let subtitleHideTimeout = null;

// ============ Push-to-Talk State ============

let pushToTalkActive = false;
let micOverlay = null;
let micTranscriptEl = null;
let lastPushToTalkTranscript = "";
let pushToTalkStopReason = "released";

// ============ Message Listener ============

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "SHOW_CURSOR") {
    showCursor(message.x, message.y, message.label);
    sendResponse({ success: true });
  }

  if (message.type === "HIDE_CURSOR") {
    hideCursor();
    sendResponse({ success: true });
  }

  if (message.type === "SHOW_SUBTITLE") {
    showSubtitle(message.text);
    sendResponse({ success: true });
  }

  if (message.type === "HIDE_SUBTITLE") {
    hideSubtitle();
    sendResponse({ success: true });
  }

  if (message.type === "START_VOICE_INPUT") {
    const options = message.options || {};
    if (options.pushToTalk) {
      startPushToTalk("runtime");
    } else {
      startVoiceRecognition(options);
    }
    sendResponse({ success: true });
  }

  if (message.type === "STOP_VOICE_INPUT") {
    if (pushToTalkActive) {
      stopPushToTalk("runtime");
    } else {
      stopVoiceRecognition();
    }
    sendResponse({ success: true });
  }

  // Legacy DOM context (returns null — Rive is Flutter canvas)
  if (message.type === "EXTRACT_DOM_CONTEXT") {
    sendResponse({ domContext: null });
  }

  return true;
});

// ============ Cursor Overlay ============

/**
 * Shows an animated pulsing cursor overlay at the given viewport position.
 * Used in collaborative mode (persistent) and agentic mode (brief flash).
 */
function showCursor(xPercent, yPercent, label) {
  hideCursor();

  const x = (xPercent / 100) * window.innerWidth;
  const y = (yPercent / 100) * window.innerHeight;

  cursorOverlay = document.createElement("div");
  cursorOverlay.id = "rive-navigator-cursor";
  cursorOverlay.style.cssText = `
    position: fixed;
    left: ${x}px;
    top: ${y}px;
    z-index: 2147483647;
    pointer-events: none;
    transform: translate(-50%, -50%);
    transition: left 0.3s ease-out, top 0.3s ease-out;
  `;

  cursorRing = document.createElement("div");
  cursorRing.style.cssText = `
    width: 80px;
    height: 80px;
    border-radius: 50%;
    border: 3px solid #7c3aed;
    background: rgba(124, 58, 237, 0.12);
    animation: rive-nav-pulse 1.5s ease-in-out infinite;
    position: relative;
  `;

  const dot = document.createElement("div");
  dot.style.cssText = `
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: #7c3aed;
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    box-shadow: 0 0 8px rgba(124, 58, 237, 0.6);
  `;
  cursorRing.appendChild(dot);

  if (label) {
    cursorLabel = document.createElement("div");
    cursorLabel.style.cssText = `
      position: absolute;
      top: 88px;
      left: 50%;
      transform: translateX(-50%);
      background: #1a1a2e;
      color: #e4e4e7;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 11px;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 6px;
      border: 1px solid #7c3aed;
      white-space: nowrap;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
      pointer-events: none;
    `;
    cursorLabel.textContent = label;
    cursorOverlay.appendChild(cursorLabel);
  }

  cursorOverlay.appendChild(cursorRing);

  if (!document.getElementById("rive-nav-cursor-styles")) {
    const style = document.createElement("style");
    style.id = "rive-nav-cursor-styles";
    style.textContent = `
      @keyframes rive-nav-pulse {
        0% { transform: scale(1); opacity: 1; border-color: #7c3aed; }
        50% { transform: scale(1.3); opacity: 0.6; border-color: #a78bfa; }
        100% { transform: scale(1); opacity: 1; border-color: #7c3aed; }
      }
    `;
    document.head.appendChild(style);
  }

  document.body.appendChild(cursorOverlay);

  hideTimeout = setTimeout(() => hideCursor(), 15000);
}

function hideCursor() {
  if (hideTimeout) {
    clearTimeout(hideTimeout);
    hideTimeout = null;
  }
  if (cursorOverlay) {
    cursorOverlay.style.transition = "opacity 0.2s ease-out";
    cursorOverlay.style.opacity = "0";
    setTimeout(() => {
      cursorOverlay?.remove();
      cursorOverlay = null;
      cursorRing = null;
      cursorLabel = null;
    }, 200);
  }
}

// Auto-hide cursor on user click (collaborative mode)
document.addEventListener(
  "click",
  () => {
    if (cursorOverlay) hideCursor();
  },
  { capture: true }
);

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && cursorOverlay) hideCursor();

  // Push-to-talk: Ctrl+Space (hold to record, release to send)
  if (e.code === "Space" && e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
    e.preventDefault();
    startPushToTalk("page");
  }
});

document.addEventListener("keyup", (e) => {
  // Release Ctrl or Space ends push-to-talk
  if (pushToTalkActive && (e.code === "Space" || e.key === "Control")) {
    stopPushToTalk(`${e.code}/${e.key}`);
  }
});

// ============ Subtitle Overlay ============

/**
 * Shows a subtitle bar at the bottom center of the viewport.
 * Used for audio narration text display on the Rive editor page.
 * Non-interactive (pointer-events: none) so it doesn't block editor usage.
 */
function showSubtitle(text) {
  hideSubtitle();

  // Truncate for display (full text goes to TTS)
  const displayText = text.length > 200 ? text.substring(0, 197) + "..." : text;

  // Inject styles if not already present
  if (!document.getElementById("rive-nav-subtitle-styles")) {
    const style = document.createElement("style");
    style.id = "rive-nav-subtitle-styles";
    style.textContent = `
      @keyframes rive-nav-subtitle-fadein {
        from { opacity: 0; transform: translate(-50%, 10px); }
        to   { opacity: 1; transform: translate(-50%, 0); }
      }
      @keyframes rive-nav-subtitle-fadeout {
        from { opacity: 1; transform: translate(-50%, 0); }
        to   { opacity: 0; transform: translate(-50%, 10px); }
      }
    `;
    document.head.appendChild(style);
  }

  subtitleOverlay = document.createElement("div");
  subtitleOverlay.id = "rive-navigator-subtitle";
  subtitleOverlay.style.cssText = `
    position: fixed;
    bottom: 32px;
    left: 50%;
    transform: translate(-50%, 0);
    z-index: 2147483646;
    pointer-events: none;
    max-width: 70%;
    padding: 10px 20px;
    background: rgba(10, 10, 20, 0.85);
    color: #f0f0f5;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    border-radius: 10px;
    border: 1px solid rgba(124, 58, 237, 0.5);
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5), 0 0 10px rgba(124, 58, 237, 0.15);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    animation: rive-nav-subtitle-fadein 0.3s ease-out forwards;
    text-align: center;
    word-wrap: break-word;
  `;

  // Purple accent bar at top
  const accent = document.createElement("div");
  accent.style.cssText = `
    position: absolute;
    top: 0;
    left: 16px;
    right: 16px;
    height: 2px;
    background: linear-gradient(90deg, transparent, #7c3aed, transparent);
    border-radius: 1px;
  `;
  subtitleOverlay.appendChild(accent);

  // Speaker icon + text
  const content = document.createElement("span");
  content.textContent = `🔊 ${displayText}`;
  subtitleOverlay.appendChild(content);

  document.body.appendChild(subtitleOverlay);

  // Safety auto-hide after 30 seconds (in case hideSubtitle is never called)
  subtitleHideTimeout = setTimeout(() => hideSubtitle(), 30000);
}

/**
 * Hides the subtitle overlay with a fade-out animation.
 */
function hideSubtitle() {
  if (subtitleHideTimeout) {
    clearTimeout(subtitleHideTimeout);
    subtitleHideTimeout = null;
  }

  if (subtitleOverlay) {
    subtitleOverlay.style.animation = "rive-nav-subtitle-fadeout 0.3s ease-out forwards";
    const overlay = subtitleOverlay;
    subtitleOverlay = null;
    setTimeout(() => {
      overlay?.remove();
    }, 300);
  }
}

// ============ Voice Input (Speech Recognition) ============

/**
 * Runs speech recognition on the Rive page (https:// origin).
 * Chrome extension sidepanels cannot access the microphone because they run
 * under the chrome-extension:// protocol. The content script runs on the
 * actual web page, which has normal mic permissions.
 *
 * Results are sent back to the sidebar via chrome.runtime.sendMessage().
 */
let voiceRecognition = null;

function startPushToTalk(source = "unknown") {
  if (pushToTalkActive) return;

  pushToTalkActive = true;
  pushToTalkStopReason = "released";
  lastPushToTalkTranscript = "";
  showMicOverlay();

  // Tell sidebar we're recording so VOICE_RESULT messages are accepted.
  chrome.runtime.sendMessage({ type: "PUSH_TO_TALK_START" });
  startVoiceRecognition({ continuous: true, pushToTalk: true });
}

function stopPushToTalk(reason = "released") {
  if (!pushToTalkActive) return;

  pushToTalkActive = false;
  pushToTalkStopReason = reason;
  hideMicOverlay();
  stopVoiceRecognition();
}

/**
 * @param {Object} [options]
 * @param {boolean} [options.continuous=false] - Keep listening until manually stopped
 * @param {boolean} [options.pushToTalk=false] - Update the on-page mic overlay with live transcript
 */
function startVoiceRecognition(options = {}) {
  stopVoiceRecognition();

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    chrome.runtime.sendMessage({
      type: "VOICE_ERROR",
      error: "Voice input is not supported in this browser. Try Chrome or Edge.",
    });
    return;
  }

  const recognition = new SpeechRecognition();
  voiceRecognition = recognition;
  recognition.continuous = !!options.continuous;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  recognition.onresult = (event) => {
    let transcript = "";
    let isFinal = false;
    for (let i = 0; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
      if (event.results[i].isFinal) isFinal = true;
    }

    // Update on-page mic overlay with live transcript
    if (options.pushToTalk && transcript) {
      lastPushToTalkTranscript = transcript;
      updateMicTranscript(transcript);
    }

    const sendFinal = options.pushToTalk ? false : isFinal;

    // In push-to-talk mode, NEVER send isFinal from onresult.
    // Individual segments finalize while the user is still holding the key.
    // Only onend (triggered by keyup → abort) should send the final signal.
    chrome.runtime.sendMessage({
      type: "VOICE_RESULT",
      transcript,
      isFinal: sendFinal,
    });
  };

  recognition.onend = () => {
    // In push-to-talk mode, send the full accumulated transcript as final
    const finalTranscript = options.pushToTalk ? lastPushToTalkTranscript : "";
    chrome.runtime.sendMessage({
      type: "VOICE_RESULT",
      transcript: finalTranscript,
      isFinal: true,
    });
    if (voiceRecognition === recognition) {
      voiceRecognition = null;
    }
  };

  recognition.onerror = (event) => {
    if (voiceRecognition === recognition) {
      voiceRecognition = null;
    }
    if (event.error === "not-allowed") {
      chrome.runtime.sendMessage({
        type: "VOICE_ERROR",
        error: "Microphone access denied. Please click the lock icon in the address bar, allow microphone for this site, and try again.",
      });
    } else if (event.error !== "no-speech" && event.error !== "aborted") {
      chrome.runtime.sendMessage({
        type: "VOICE_ERROR",
        error: `Speech recognition error: ${event.error}`,
      });
    }
  };

  recognition.start();
  console.log("[Rive Navigator] Voice recognition started on page");
}

function stopVoiceRecognition() {
  const recognition = voiceRecognition;
  if (recognition) {
    recognition.abort();
    if (voiceRecognition === recognition) {
      voiceRecognition = null;
    }
    console.log("[Rive Navigator] Voice recognition stopped");
  }
}

// ============ Push-to-Talk Mic Overlay ============

/**
 * Shows a large pulsing mic icon centered on the page with live transcript.
 * Appears when the user holds Ctrl+Space for push-to-talk.
 */
function showMicOverlay() {
  hideMicOverlay();

  // Inject keyframe styles
  if (!document.getElementById("rive-nav-mic-styles")) {
    const style = document.createElement("style");
    style.id = "rive-nav-mic-styles";
    style.textContent = `
      @keyframes rive-nav-mic-pulse {
        0%   { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
        70%  { box-shadow: 0 0 0 20px rgba(239, 68, 68, 0); }
        100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
      }
      @keyframes rive-nav-mic-fadein {
        from { opacity: 0; transform: translate(-50%, -50%) scale(0.8); }
        to   { opacity: 1; transform: translate(-50%, -50%) scale(1); }
      }
    `;
    document.head.appendChild(style);
  }

  micOverlay = document.createElement("div");
  micOverlay.id = "rive-navigator-mic";
  micOverlay.style.cssText = `
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    z-index: 2147483647;
    pointer-events: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
    animation: rive-nav-mic-fadein 0.2s ease-out forwards;
  `;

  // Pulsing mic circle
  const micCircle = document.createElement("div");
  micCircle.style.cssText = `
    width: 80px;
    height: 80px;
    border-radius: 50%;
    background: rgba(239, 68, 68, 0.15);
    border: 3px solid #ef4444;
    display: flex;
    align-items: center;
    justify-content: center;
    animation: rive-nav-mic-pulse 1.5s ease-out infinite;
  `;

  // Mic SVG icon
  micCircle.innerHTML = `
    <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
      <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
      <line x1="12" y1="19" x2="12" y2="23"/>
      <line x1="8" y1="23" x2="16" y2="23"/>
    </svg>
  `;

  micOverlay.appendChild(micCircle);

  // Live transcript text
  micTranscriptEl = document.createElement("div");
  micTranscriptEl.style.cssText = `
    max-width: 500px;
    padding: 8px 16px;
    background: rgba(10, 10, 20, 0.85);
    color: #f0f0f5;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 16px;
    line-height: 1.4;
    border-radius: 8px;
    border: 1px solid rgba(239, 68, 68, 0.4);
    text-align: center;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    min-height: 24px;
  `;
  micTranscriptEl.textContent = "Listening...";
  micOverlay.appendChild(micTranscriptEl);

  // Shortcut hint
  const hint = document.createElement("div");
  hint.style.cssText = `
    font-size: 11px;
    color: rgba(240, 240, 245, 0.5);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  `;
  hint.textContent = "Release Ctrl+Space to send";
  micOverlay.appendChild(hint);

  document.body.appendChild(micOverlay);
}

/**
 * Updates the live transcript text in the mic overlay.
 */
function updateMicTranscript(text) {
  if (micTranscriptEl) {
    micTranscriptEl.textContent = text || "Listening...";
  }
}

/**
 * Hides the mic overlay.
 */
function hideMicOverlay() {
  if (micOverlay) {
    micOverlay.remove();
    micOverlay = null;
    micTranscriptEl = null;
  }
}

// ============ Init ============

console.log(
  "[Rive Navigator] Content script loaded (cursor overlay ready) on",
  window.location.href
);
