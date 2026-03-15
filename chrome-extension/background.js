/**
 * Rive UI Navigator - Background Service Worker
 * Handles sidebar panel opening, screenshot capture, and CDP-based action execution.
 *
 * Actions (click, drag, key, type) are executed via Chrome DevTools Protocol (CDP)
 * so events appear as trusted browser input (isTrusted: true). This is critical
 * for Flutter Web apps like Rive which ignore synthetic JavaScript events.
 */

// ============ Debugger State ============

// Track which tabs have the debugger attached
const attachedTabs = new Set();

// ============ Extension Lifecycle ============

// Open sidebar when extension icon is clicked
chrome.action.onClicked.addListener(async (tab) => {
  await chrome.sidePanel.open({ tabId: tab.id });
});

// Set sidebar to open automatically on Rive domains
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

// Clean up debugger when tab closes
chrome.tabs.onRemoved.addListener((tabId) => {
  if (attachedTabs.has(tabId)) {
    attachedTabs.delete(tabId);
    console.log(`[Background] Tab ${tabId} closed, cleaned up debugger tracking`);
  }
});

// Track when debugger is detached (by user or Chrome)
chrome.debugger.onDetach.addListener((source, reason) => {
  if (source.tabId) {
    attachedTabs.delete(source.tabId);
    console.log(`[Background] Debugger detached from tab ${source.tabId}: ${reason}`);
  }
});

// ============ Message Listener ============

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "CAPTURE_SCREENSHOT") {
    handleScreenshotCapture(message, sender, sendResponse);
    return true;
  }

  if (message.type === "GET_DOM_CONTEXT") {
    handleDomContextRequest(message, sender, sendResponse);
    return true;
  }

  if (message.type === "SEND_TO_AGENT") {
    handleAgentMessage(message, sender, sendResponse);
    return true;
  }

  if (message.type === "IMPORT_SVG_VIA_PASTE") {
    handleSvgPasteImport(message, sender, sendResponse);
    return true;
  }

  if (message.type === "SHOW_CURSOR" || message.type === "HIDE_CURSOR") {
    handleCursorMessage(message, sender, sendResponse);
    return true;
  }

  if (message.type === "SHOW_SUBTITLE" || message.type === "HIDE_SUBTITLE") {
    handleSubtitleMessage(message, sender, sendResponse);
    return true;
  }

  if (message.type === "START_VOICE_INPUT" || message.type === "STOP_VOICE_INPUT") {
    handleVoiceInputRelay(message, sender, sendResponse);
    return true;
  }

  if (message.type === "EXECUTE_ACTION") {
    handleExecuteAction(message, sender, sendResponse);
    return true;
  }
});

// ============ CDP Action Execution ============

/**
 * Executes an action on the active Rive tab using Chrome DevTools Protocol.
 * This produces trusted browser events that Flutter Web recognizes.
 */
async function handleExecuteAction(message, sender, sendResponse) {
  try {
    const action = message.action;
    if (!action || !action.type) {
      sendResponse({ success: false, error: "No action type specified" });
      return;
    }

    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      sendResponse({ success: false, error: "No active tab found" });
      return;
    }

    console.log(`[Background] CDP Action: ${action.type} — "${action.label || ""}"`);

    // Show visual cursor feedback via content script (non-blocking)
    if (action.x !== undefined && action.y !== undefined) {
      showCursorBriefly(tab.id, action.x, action.y, action.label);
    } else if (action.x1 !== undefined && action.y1 !== undefined) {
      showCursorBriefly(tab.id, action.x1, action.y1, action.label);
    }

    // Ensure debugger is attached
    await ensureDebuggerAttached(tab.id);

    // Get viewport size for coordinate conversion
    const viewport = await getViewportSize(tab.id);
    console.log(`[Background] Viewport: ${viewport.width}x${viewport.height}`);

    // Execute the action via CDP
    let result;
    switch (action.type) {
      case "click":
        result = await cdpClick(tab.id, action, viewport);
        break;
      case "doubleclick":
        result = await cdpDoubleClick(tab.id, action, viewport);
        break;
      case "drag":
        result = await cdpDrag(tab.id, action, viewport);
        break;
      case "key":
        result = await cdpKey(tab.id, action);
        break;
      case "type":
        result = await cdpType(tab.id, action, viewport);
        break;
      case "hover":
        result = await cdpHover(tab.id, action, viewport);
        break;
      case "wait":
        await sleep(action.duration || 500);
        result = { success: true, action: "wait" };
        break;
      default:
        result = { success: false, error: `Unknown action: ${action.type}` };
    }

    console.log(`[Background] CDP Result:`, result);
    sendResponse(result);
  } catch (error) {
    console.error("[Background] CDP Action failed:", error);
    sendResponse({ success: false, error: error.message });
  }
}

/**
 * Ensures the Chrome debugger is attached to the target tab.
 */
async function ensureDebuggerAttached(tabId) {
  if (attachedTabs.has(tabId)) return;

  try {
    await chrome.debugger.attach({ tabId }, "1.3");
    attachedTabs.add(tabId);
    console.log(`[Background] Debugger attached to tab ${tabId}`);
  } catch (error) {
    // Already attached (e.g., by DevTools)
    if (error.message.includes("already attached")) {
      attachedTabs.add(tabId);
      console.log(`[Background] Debugger already attached to tab ${tabId}`);
    } else {
      throw error;
    }
  }
}

/**
 * Gets the viewport size of the page via CDP.
 */
async function getViewportSize(tabId) {
  const result = await chrome.debugger.sendCommand({ tabId }, "Runtime.evaluate", {
    expression: "JSON.stringify({ width: window.innerWidth, height: window.innerHeight })",
    returnByValue: true,
  });

  try {
    return JSON.parse(result.result.value);
  } catch {
    // Fallback to reasonable defaults
    return { width: 1920, height: 1080 };
  }
}

/**
 * Converts percentage coordinates to pixel coordinates.
 * Includes validation: if a value > 100, the agent likely output pixel coords
 * instead of percentages — we auto-correct by treating them as pixels directly.
 */
function percentToPixels(xPercent, yPercent, viewport) {
  let x, y;

  // Detect pixel vs percentage confusion: percentages should be 0-100
  if (xPercent > 100 || yPercent > 100) {
    console.warn(`[Background] Coordinate validation: (${xPercent}, ${yPercent}) looks like pixels, not percentages. Using as-is.`);
    x = Math.round(Math.min(xPercent, viewport.width));
    y = Math.round(Math.min(yPercent, viewport.height));
  } else {
    x = Math.round((xPercent / 100) * viewport.width);
    y = Math.round((yPercent / 100) * viewport.height);
  }

  // Clamp to viewport bounds
  x = Math.max(0, Math.min(x, viewport.width - 1));
  y = Math.max(0, Math.min(y, viewport.height - 1));

  return { x, y };
}

/**
 * CDP Click — dispatches mousePressed + mouseReleased at (x%, y%).
 */
async function cdpClick(tabId, action, viewport) {
  const { x, y } = percentToPixels(action.x, action.y, viewport);

  // Wait for cursor animation
  await sleep(350);

  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mousePressed",
    x,
    y,
    button: "left",
    clickCount: 1,
  });

  await sleep(50);

  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x,
    y,
    button: "left",
    clickCount: 1,
  });

  console.log(`[Background] CDP Click at (${x}, ${y}) — "${action.label}"`);
  return { success: true, action: "click", x, y };
}

/**
 * CDP Hover — moves the mouse to (x%, y%) without clicking.
 * Used to trigger hover states in the Rive editor, such as revealing
 * the transition connector dot on state machine nodes.
 * After moving, waits 500ms to let the UI react before the screenshot is taken.
 */
async function cdpHover(tabId, action, viewport) {
  const { x, y } = percentToPixels(action.x, action.y, viewport);

  // Wait for cursor animation
  await sleep(350);

  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x,
    y,
  });

  // Wait for hover effects to appear (connector dots, tooltips, etc.)
  await sleep(500);

  console.log(`[Background] CDP Hover at (${x}, ${y}) — "${action.label}"`);
  return { success: true, action: "hover", x, y };
}

/**
 * CDP Double-click — click to select, pause to let selection settle, then double-click.
 *
 * Rive (Flutter Web) needs the item to be in a "settled selected" state before
 * a double-click triggers rename/edit mode. A rapid double-click (50ms gap) is
 * interpreted as a selection action, not a rename gesture.
 */
async function cdpDoubleClick(tabId, action, viewport) {
  const { x, y } = percentToPixels(action.x, action.y, viewport);

  await sleep(350);

  // Step 1: Click to select the item
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mousePressed",
    x,
    y,
    button: "left",
    clickCount: 1,
  });
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x,
    y,
    button: "left",
    clickCount: 1,
  });

  // Step 2: Pause to let selection settle (critical for rename/edit mode)
  await sleep(400);

  // Step 3: Double-click the already-selected item to enter edit/rename mode
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mousePressed",
    x,
    y,
    button: "left",
    clickCount: 1,
  });
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x,
    y,
    button: "left",
    clickCount: 1,
  });

  await sleep(50);

  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mousePressed",
    x,
    y,
    button: "left",
    clickCount: 2,
  });
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x,
    y,
    button: "left",
    clickCount: 2,
  });

  console.log(`[Background] CDP Double-click at (${x}, ${y}) — select → pause → double-click — "${action.label}"`);
  return { success: true, action: "doubleclick", x, y };
}

/**
 * CDP Drag — mousePressed at start, animated mouseMoved steps, mouseReleased at end.
 */
async function cdpDrag(tabId, action, viewport) {
  const start = percentToPixels(action.x1, action.y1, viewport);
  const end = percentToPixels(action.x2, action.y2, viewport);

  await sleep(350);

  // Mouse down at start position
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: start.x,
    y: start.y,
    button: "left",
    clickCount: 1,
  });

  // Animated move (10 steps)
  const steps = 10;
  for (let i = 1; i <= steps; i++) {
    const progress = i / steps;
    const cx = Math.round(start.x + (end.x - start.x) * progress);
    const cy = Math.round(start.y + (end.y - start.y) * progress);

    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: cx,
      y: cy,
      button: "left",
      buttons: 1, // Left button held
    });

    await sleep(30);
  }

  // Mouse up at end position
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: end.x,
    y: end.y,
    button: "left",
    clickCount: 1,
  });

  console.log(`[Background] CDP Drag (${start.x},${start.y}) → (${end.x},${end.y}) — "${action.label}"`);
  return { success: true, action: "drag", start, end };
}

/**
 * CDP Key — dispatches keyDown + keyUp via Input.dispatchKeyEvent.
 * This produces trusted keyboard events that Flutter Web recognizes.
 */
async function cdpKey(tabId, action) {
  const key = action.key;
  const mods = (action.modifiers || "").split(",").map((m) => m.trim().toLowerCase());
  const commands = Array.isArray(action.commands) ? action.commands : [];

  // Build modifier flags
  let modifierFlags = 0;
  if (mods.includes("alt")) modifierFlags |= 1;
  if (mods.includes("ctrl")) modifierFlags |= 2;
  if (mods.includes("meta") || mods.includes("cmd")) modifierFlags |= 4;
  if (mods.includes("shift")) modifierFlags |= 8;

  // Map key to proper CDP key parameters
  const keyInfo = getKeyInfo(key);

  // Press modifier keys first
  if (mods.includes("ctrl")) {
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Control",
      code: "ControlLeft",
      windowsVirtualKeyCode: 17,
      nativeVirtualKeyCode: 17,
      modifiers: modifierFlags,
    });
  }
  if (mods.includes("meta") || mods.includes("cmd")) {
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Meta",
      code: "MetaLeft",
      windowsVirtualKeyCode: 91,
      nativeVirtualKeyCode: 91,
      modifiers: modifierFlags,
    });
  }
  if (mods.includes("shift")) {
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Shift",
      code: "ShiftLeft",
      windowsVirtualKeyCode: 16,
      nativeVirtualKeyCode: 16,
      modifiers: modifierFlags,
    });
  }
  if (mods.includes("alt")) {
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Alt",
      code: "AltLeft",
      windowsVirtualKeyCode: 18,
      nativeVirtualKeyCode: 18,
      modifiers: modifierFlags,
    });
  }

  // Key down
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    type: "keyDown",
    key: keyInfo.key,
    code: keyInfo.code,
    windowsVirtualKeyCode: keyInfo.keyCode,
    nativeVirtualKeyCode: keyInfo.keyCode,
    modifiers: modifierFlags,
    text: keyInfo.text,
    unmodifiedText: keyInfo.text,
    commands,
  });

  await sleep(50);

  // Key up
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    type: "keyUp",
    key: keyInfo.key,
    code: keyInfo.code,
    windowsVirtualKeyCode: keyInfo.keyCode,
    nativeVirtualKeyCode: keyInfo.keyCode,
    modifiers: modifierFlags,
  });

  // Release modifier keys
  if (mods.includes("alt")) {
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyUp", key: "Alt", code: "AltLeft",
      windowsVirtualKeyCode: 18, nativeVirtualKeyCode: 18,
    });
  }
  if (mods.includes("shift")) {
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyUp", key: "Shift", code: "ShiftLeft",
      windowsVirtualKeyCode: 16, nativeVirtualKeyCode: 16,
    });
  }
  if (mods.includes("meta") || mods.includes("cmd")) {
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyUp", key: "Meta", code: "MetaLeft",
      windowsVirtualKeyCode: 91, nativeVirtualKeyCode: 91,
    });
  }
  if (mods.includes("ctrl")) {
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyUp", key: "Control", code: "ControlLeft",
      windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17,
    });
  }

  console.log(`[Background] CDP Key: ${action.modifiers ? action.modifiers + "+" : ""}${key} — "${action.label}"`);
  return { success: true, action: "key", key, modifiers: action.modifiers, commands };
}

/**
 * CDP Type — ATOMIC field value entry.
 *
 * Flutter Web handles text input through a hidden <input> element, not through
 * keyboard events on the canvas. This function uses CDP's Input.insertText
 * which works at the text input system level — exactly how Flutter receives text.
 *
 * Full atomic sequence:
 * 1. If x,y provided: triple-click to focus the field AND select all text in it
 * 2. Wait for Flutter to create/focus hidden input element (200ms)
 * 3. Delete selected text (Backspace)
 * 4. Insert new text via Input.insertText (Flutter's hidden input receives this)
 * 5. Press Enter to confirm
 *
 * CRITICAL: We use triple-click (not Cmd+A) to select text. Cmd+A in Rive selects
 * all OBJECTS ON THE CANVAS — if the field click misses, Cmd+A + Backspace would
 * delete every shape the user drew. Triple-click only selects text within the
 * focused input field, making it safe even if the click target is slightly off.
 */
async function cdpType(tabId, action, viewport) {
  const text = action.text;
  if (!text) return { success: false, error: "No text to type" };

  // Step 1: If coordinates provided, triple-click to focus AND select all text
  // Triple-click selects all text within the field — safe for canvas objects.
  // Unlike Cmd+A which selects canvas objects, triple-click only affects text.
  if (action.x !== undefined && action.y !== undefined && viewport) {
    const { x, y } = percentToPixels(action.x, action.y, viewport);
    console.log(`[Background] CDP Type: triple-clicking field at (${x}, ${y}) to focus and select`);

    // Single click (focus)
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
      type: "mousePressed",
      x,
      y,
      button: "left",
      clickCount: 1,
    });
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
      type: "mouseReleased",
      x,
      y,
      button: "left",
      clickCount: 1,
    });

    // Wait for Flutter to create and focus its hidden input element
    await sleep(200);

    // Double click (select word)
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
      type: "mousePressed",
      x,
      y,
      button: "left",
      clickCount: 2,
    });
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
      type: "mouseReleased",
      x,
      y,
      button: "left",
      clickCount: 2,
    });
    await sleep(50);

    // Triple click (select all text in field)
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
      type: "mousePressed",
      x,
      y,
      button: "left",
      clickCount: 3,
    });
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
      type: "mouseReleased",
      x,
      y,
      button: "left",
      clickCount: 3,
    });
    await sleep(100);
  } else {
    // No coordinates — field should already be focused
    // Use Home + Shift+End to select all text in the current field
    // This is safer than Cmd+A which would select canvas objects
    console.log(`[Background] CDP Type: selecting text with Home + Shift+End`);

    // Home — move cursor to start of field
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Home",
      code: "Home",
      windowsVirtualKeyCode: 36,
      nativeVirtualKeyCode: 36,
    });
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "Home",
      code: "Home",
      windowsVirtualKeyCode: 36,
      nativeVirtualKeyCode: 36,
    });
    await sleep(30);

    // Shift+End — select from cursor to end of field
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "End",
      code: "End",
      windowsVirtualKeyCode: 35,
      nativeVirtualKeyCode: 35,
      modifiers: 8, // Shift
    });
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "End",
      code: "End",
      windowsVirtualKeyCode: 35,
      nativeVirtualKeyCode: 35,
      modifiers: 8,
    });
    await sleep(50);
  }

  // Step 2: Clear existing text ONLY if a text input is actually focused.
  // Flutter Web creates a hidden <input> element when editing text fields.
  // The hidden input may live inside a shadow DOM (e.g. inside <flt-glass-pane>),
  // so we walk activeElement through shadow roots to find the real focused element.
  let textFieldFocused = false;
  try {
    const focusCheck = await chrome.debugger.sendCommand({ tabId }, "Runtime.evaluate", {
      expression: `(function() {
        let el = document.activeElement;
        while (el && el.shadowRoot && el.shadowRoot.activeElement) {
          el = el.shadowRoot.activeElement;
        }
        return el ? el.tagName : 'NONE';
      })()`,
      returnByValue: true,
    });
    const activeTag = (focusCheck?.result?.value || "NONE").toUpperCase();
    textFieldFocused = (activeTag === "INPUT" || activeTag === "TEXTAREA");
    console.log(`[Background] CDP Type: deepActiveElement = ${activeTag}, textFieldFocused = ${textFieldFocused}`);
  } catch (e) {
    console.warn(`[Background] CDP Type: could not check activeElement: ${e.message}`);
  }

  if (textFieldFocused) {
    // Belt-and-suspenders: Cmd/Ctrl+A inside the focused input to ensure ALL
    // text is selected, even if the triple-click only partially selected.
    // This is safe because Cmd+A inside a focused <input> selects its text,
    // NOT canvas objects.
    const platform = await chrome.runtime.getPlatformInfo();
    const selectAllModifiers = platform.os === "mac" ? 4 : 2; // 4 = Meta (Cmd), 2 = Ctrl
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "a",
      code: "KeyA",
      windowsVirtualKeyCode: 65,
      nativeVirtualKeyCode: 65,
      modifiers: selectAllModifiers,
    });
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "a",
      code: "KeyA",
      windowsVirtualKeyCode: 65,
      nativeVirtualKeyCode: 65,
      modifiers: selectAllModifiers,
    });
    await sleep(30);

    // Now delete the fully-selected text
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Backspace",
      code: "Backspace",
      windowsVirtualKeyCode: 8,
      nativeVirtualKeyCode: 8,
    });
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "Backspace",
      code: "Backspace",
      windowsVirtualKeyCode: 8,
      nativeVirtualKeyCode: 8,
    });
    await sleep(50);
  } else {
    console.log(`[Background] CDP Type: No text field focused — skipping clear (safety)`);
  }

  // Step 3: Insert text via Input.insertText
  // If text was selected (by triple-click or Backspace cleared it), this replaces/inserts.
  // This works at the text input system level — Flutter's hidden <input> receives it
  // directly through the browser's text input pipeline, not as keyboard events.
  console.log(`[Background] CDP Type: inserting text "${text}" via Input.insertText`);
  await chrome.debugger.sendCommand({ tabId }, "Input.insertText", {
    text: text,
  });
  await sleep(100);

  // Step 4: Press Enter to confirm the value
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
    text: "\r",
  });
  await sleep(30);
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });

  console.log(`[Background] CDP Type: "${text}" (triple-click → ${textFieldFocused ? 'backspace → ' : ''}insert → enter) — "${action.label}"`);
  return { success: true, action: "type", text };
}

// ============ Key Mapping ============

/**
 * Maps a key character/name to CDP key event properties.
 */
function getKeyInfo(key) {
  // Single character keys
  if (key.length === 1) {
    const upper = key.toUpperCase();
    if (upper >= "A" && upper <= "Z") {
      return {
        key: key.toLowerCase(),
        code: `Key${upper}`,
        keyCode: upper.charCodeAt(0),
        text: key.toLowerCase(),
      };
    }
    if (upper >= "0" && upper <= "9") {
      return {
        key: key,
        code: `Digit${key}`,
        keyCode: key.charCodeAt(0),
        text: key,
      };
    }
    // Special characters
    const charMap = {
      " ": { key: " ", code: "Space", keyCode: 32, text: " " },
      "+": { key: "+", code: "Equal", keyCode: 187, text: "+" },
      "-": { key: "-", code: "Minus", keyCode: 189, text: "-" },
      "=": { key: "=", code: "Equal", keyCode: 187, text: "=" },
      ".": { key: ".", code: "Period", keyCode: 190, text: "." },
      ",": { key: ",", code: "Comma", keyCode: 188, text: "," },
      "/": { key: "/", code: "Slash", keyCode: 191, text: "/" },
    };
    if (charMap[key]) return charMap[key];

    // Fallback for any other single char
    return {
      key: key,
      code: key,
      keyCode: key.charCodeAt(0),
      text: key,
    };
  }

  // Named keys
  const namedKeys = {
    Enter: { key: "Enter", code: "Enter", keyCode: 13, text: "\r" },
    Escape: { key: "Escape", code: "Escape", keyCode: 27, text: "" },
    Backspace: { key: "Backspace", code: "Backspace", keyCode: 8, text: "" },
    Tab: { key: "Tab", code: "Tab", keyCode: 9, text: "\t" },
    Space: { key: " ", code: "Space", keyCode: 32, text: " " },
    Delete: { key: "Delete", code: "Delete", keyCode: 46, text: "" },
    ArrowUp: { key: "ArrowUp", code: "ArrowUp", keyCode: 38, text: "" },
    ArrowDown: { key: "ArrowDown", code: "ArrowDown", keyCode: 40, text: "" },
    ArrowLeft: { key: "ArrowLeft", code: "ArrowLeft", keyCode: 37, text: "" },
    ArrowRight: { key: "ArrowRight", code: "ArrowRight", keyCode: 39, text: "" },
  };

  if (namedKeys[key]) return namedKeys[key];

  // Fallback
  return { key: key, code: key, keyCode: 0, text: "" };
}

// ============ Visual Cursor Feedback ============

/**
 * Shows cursor overlay briefly on the content page for visual feedback
 * during agentic execution, then hides it.
 */
async function showCursorBriefly(tabId, xPercent, yPercent, label) {
  try {
    await chrome.tabs.sendMessage(tabId, {
      type: "SHOW_CURSOR",
      x: xPercent,
      y: yPercent,
      label: label || "",
    });

    // Auto-hide after 600ms
    setTimeout(async () => {
      try {
        await chrome.tabs.sendMessage(tabId, { type: "HIDE_CURSOR" });
      } catch {
        // Tab may have navigated
      }
    }, 600);
  } catch {
    // Content script not loaded — skip visual feedback
    console.warn("[Background] Could not show cursor (content script not ready)");
  }
}

// ============ Screenshot Capture ============

/**
 * Captures a screenshot of the active Rive tab.
 */
async function handleScreenshotCapture(message, sender, sendResponse) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      sendResponse({ error: "No active tab found" });
      return;
    }

    const dataUrl = await chrome.tabs.captureVisibleTab(null, {
      format: "png",
      quality: 90,
    });

    sendResponse({ screenshot: dataUrl, tabId: tab.id, url: tab.url });
  } catch (error) {
    console.error("Screenshot capture failed:", error);
    sendResponse({ error: error.message });
  }
}

// ============ DOM Context ============

/**
 * Requests DOM context from the content script on the Rive page.
 */
async function handleDomContextRequest(message, sender, sendResponse) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      sendResponse({ error: "No active tab found" });
      return;
    }

    const response = await chrome.tabs.sendMessage(tab.id, {
      type: "EXTRACT_DOM_CONTEXT",
    });

    sendResponse(response);
  } catch (error) {
    console.error("DOM context extraction failed:", error);
    sendResponse({ error: error.message, domContext: null });
  }
}

// ============ Agent Communication ============

/**
 * Sends the user's message + screenshot + DOM context to the ADK agent backend.
 */
async function handleAgentMessage(message, sender, sendResponse) {
  try {
    const { userMessage, screenshot, domContext, sessionId, taskMode, model } =
      message.payload;

    const AGENT_API_URL = await getAgentApiUrl();

    const response = await fetch(`${AGENT_API_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: userMessage,
        screenshot: screenshot,
        dom_context: domContext,
        session_id: sessionId,
        user_id: "extension_user",
        task_mode: taskMode || "collaborative",
        model: model || "gemini-3-flash-preview",
      }),
    });

    if (!response.ok) {
      throw new Error(`Agent API responded with ${response.status}`);
    }

    const data = await response.json();
    sendResponse({ agentResponse: data });
  } catch (error) {
    console.error("Agent communication failed:", error);
    sendResponse({ error: error.message });
  }
}

/**
 * Pastes SVG text from the clipboard into the active Rive tab using a trusted key event.
 * The sidebar is responsible for placing the SVG markup on the clipboard first.
 */
async function handleSvgPasteImport(message, sender, sendResponse) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      sendResponse({ success: false, error: "No active Rive tab found" });
      return;
    }

    await chrome.windows.update(tab.windowId, { focused: true });
    await chrome.tabs.update(tab.id, { active: true });
    await ensureDebuggerAttached(tab.id);
    await chrome.debugger.sendCommand({ tabId: tab.id }, "Runtime.evaluate", {
      expression: `
        (() => {
          window.focus();
          document.body?.focus?.();
          document.documentElement?.focus?.();
          return document.activeElement ? document.activeElement.tagName : "NONE";
        })()
      `,
      returnByValue: true,
    });
    await sleep(80);

    const platform = await chrome.runtime.getPlatformInfo();
    const modifiers = platform.os === "mac" ? "meta" : "ctrl";
    const result = await cdpKey(tab.id, {
      type: "key",
      key: "v",
      modifiers,
      commands: ["Paste"],
      label: "Paste SVG into Rive",
    });

    sendResponse({ success: !!result.success, svgLength: message.svgLength || 0, ...result });
  } catch (error) {
    console.error("[Background] SVG paste import failed:", error);
    sendResponse({ success: false, error: error.message });
  }
}

// ============ Cursor Relay (Collaborative Mode) ============

/**
 * Relays cursor show/hide messages from the sidebar to the content script.
 */
async function handleCursorMessage(message, sender, sendResponse) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      sendResponse({ error: "No active tab found" });
      return;
    }

    const response = await chrome.tabs.sendMessage(tab.id, message);
    sendResponse(response || { success: true });
  } catch (error) {
    console.warn("[Background] Cursor relay failed:", error.message);
    sendResponse({ error: error.message });
  }
}

// ============ Voice Input Relay ============

/**
 * Relays voice input start/stop messages from the sidebar to the content script.
 * Speech recognition runs in the content script because extension sidepanels
 * (chrome-extension:// origin) cannot access the microphone.
 */
async function handleVoiceInputRelay(message, sender, sendResponse) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      sendResponse({ error: "No active tab found" });
      return;
    }

    const response = await chrome.tabs.sendMessage(tab.id, message);
    sendResponse(response || { success: true });
  } catch (error) {
    console.warn("[Background] Voice input relay failed:", error.message);
    sendResponse({ error: "Could not reach content script. Make sure you're on a Rive page." });
  }
}

// ============ Subtitle Relay ============

/**
 * Relays subtitle show/hide messages from the sidebar to the content script.
 * Same pattern as cursor relay.
 */
async function handleSubtitleMessage(message, sender, sendResponse) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      sendResponse({ error: "No active tab found" });
      return;
    }

    const response = await chrome.tabs.sendMessage(tab.id, message);
    sendResponse(response || { success: true });
  } catch (error) {
    console.warn("[Background] Subtitle relay failed:", error.message);
    sendResponse({ error: error.message });
  }
}

// ============ Helpers ============

const DEFAULT_AGENT_API_URL = "http://localhost:8000";

function normalizeAgentApiUrl(url) {
  return String(url || DEFAULT_AGENT_API_URL).trim().replace(/\/+$/, "");
}

function getAgentApiUrl() {
  return new Promise((resolve) => {
    chrome.storage.sync.get({ agentApiUrl: DEFAULT_AGENT_API_URL }, (result) => {
      resolve(normalizeAgentApiUrl(result.agentApiUrl));
    });
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
