/**
 * AGY Web Controller Frontend
 * Handles task submission, polling output stream, and managing UI state.
 */

// DOM Elements
const promptInput = document.getElementById("prompt-input");
const modelSelect = document.getElementById("model-select");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const charCount = document.getElementById("char-count");
const statusBadge = document.getElementById("status-badge");
const statusLabel = document.getElementById("status-label");
const metaTaskId = document.getElementById("meta-task-id");
const metaDuration = document.getElementById("meta-duration");
const metaExitCode = document.getElementById("meta-exit-code");
const outputConsole = document.getElementById("output-console");
const autoscrollToggle = document.getElementById("autoscroll-toggle");
const clearBtn = document.getElementById("clear-btn");
const copyBtn = document.getElementById("copy-btn");
const connectionStatus = document.getElementById("connection-status");
const connectionText = document.getElementById("connection-text");
const serverInfo = document.getElementById("server-info");

// State
let pollIntervalId = null;
let currentOffset = 0;
let isPolling = false;

// Helpers
function setConnectionState(connected, message = "Connected") {
  if (connected) {
    connectionStatus.className = "dot dot-green";
    connectionText.textContent = message;
  } else {
    connectionStatus.className = "dot dot-red";
    connectionText.textContent = message;
  }
}

function updateStatusBadge(status) {
  const normStatus = (status || "idle").toLowerCase();
  statusBadge.className = `status-badge status-${normStatus}`;
  statusLabel.textContent = normStatus.charAt(0).toUpperCase() + normStatus.slice(1);
}

function scrollToBottomIfNeeded() {
  if (autoscrollToggle.checked) {
    outputConsole.scrollTop = outputConsole.scrollHeight;
  }
}

function setActionButtonsRunning(running) {
  if (running) {
    startBtn.disabled = true;
    stopBtn.disabled = false;
    promptInput.disabled = true;
  } else {
    startBtn.disabled = false;
    stopBtn.disabled = true;
    promptInput.disabled = false;
  }
}

// Prompt input character counter and shortcut
promptInput.addEventListener("input", () => {
  const length = promptInput.value.length;
  charCount.textContent = `${length.toLocaleString()} characters`;
});

promptInput.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    if (!startBtn.disabled) {
      startTask();
    }
  }
});

// Output toolbar actions
clearBtn.addEventListener("click", () => {
  outputConsole.textContent = "";
});

copyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(outputConsole.textContent);
    const originalText = copyBtn.textContent;
    copyBtn.textContent = "Copied!";
    setTimeout(() => {
      copyBtn.textContent = originalText;
    }, 1500);
  } catch (err) {
    console.error("Clipboard copy failed:", err);
  }
});

// Polling status and incremental output
async function pollTaskStatus() {
  if (isPolling) return;
  isPolling = true;

  try {
    const res = await fetch(`/api/task/status?offset=${currentOffset}`);
    if (!res.ok) {
      throw new Error(`Status check HTTP ${res.status}`);
    }
    const data = await res.json();
    setConnectionState(true, "Connected");

    if (data.hasTask) {
      updateStatusBadge(data.status);
      metaTaskId.textContent = data.taskId || "—";
      metaDuration.textContent = `${(data.duration || 0).toFixed(1)}s`;
      metaExitCode.textContent = data.exitCode !== null && data.exitCode !== undefined ? data.exitCode : "—";

      // Append new output chunks
      if (data.output && data.output.length > 0) {
        if (currentOffset === 0) {
          // Replace initial placeholder
          outputConsole.textContent = data.output;
        } else {
          outputConsole.textContent += data.output;
        }
        currentOffset = data.offset;
        scrollToBottomIfNeeded();
      }

      // Check if task finished
      if (data.status !== "running") {
        clearInterval(pollIntervalId);
        pollIntervalId = null;
        setActionButtonsRunning(false);
      }
    } else {
      updateStatusBadge("idle");
      setActionButtonsRunning(false);
    }
  } catch (err) {
    console.error("Poll error:", err);
    setConnectionState(false, "Disconnected");
  } finally {
    isPolling = false;
  }
}

function startPolling() {
  if (pollIntervalId) clearInterval(pollIntervalId);
  pollTaskStatus();
  pollIntervalId = setInterval(pollTaskStatus, 400);
}

// Start Task
async function startTask() {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    alert("Please enter a prompt instruction.");
    promptInput.focus();
    return;
  }

  const model = modelSelect.value || undefined;

  // Reset console & state
  currentOffset = 0;
  outputConsole.textContent = `[Initiating task with AGY CLI...]\n`;
  updateStatusBadge("running");
  setActionButtonsRunning(true);
  metaTaskId.textContent = "starting...";
  metaDuration.textContent = "0.0s";
  metaExitCode.textContent = "—";

  try {
    const res = await fetch("/api/task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: jsonPayload({ prompt, model }),
    });

    const data = await res.json();
    if (!res.ok) {
      outputConsole.textContent += `\nError starting task: ${data.error || res.statusText}\n`;
      updateStatusBadge("failed");
      setActionButtonsRunning(false);
      return;
    }

    metaTaskId.textContent = data.taskId;
    startPolling();
  } catch (err) {
    outputConsole.textContent += `\nNetwork error: ${err.message}\n`;
    updateStatusBadge("failed");
    setActionButtonsRunning(false);
  }
}

// Stop Task
async function stopTask() {
  stopBtn.disabled = true;
  try {
    const res = await fetch("/api/task/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    outputConsole.textContent += `\n${data.message || "[Stop signal sent]"}\n`;
    pollTaskStatus();
  } catch (err) {
    alert(`Failed to stop task: ${err.message}`);
  }
}

function jsonPayload(obj) {
  return JSON.stringify(obj);
}

startBtn.addEventListener("click", startTask);
stopBtn.addEventListener("click", stopTask);

// Initial Health Check & state sync
async function init() {
  try {
    const res = await fetch("/api/health");
    if (res.ok) {
      const data = await res.json();
      setConnectionState(true, "Connected");
      if (data.workspace) {
        serverInfo.textContent = `Workspace: ${data.workspace.split("/").pop()}/`;
      }
      // Check existing task status
      pollTaskStatus();
    } else {
      setConnectionState(false, "Server Error");
    }
  } catch (err) {
    setConnectionState(false, "Offline");
  }
}

window.addEventListener("DOMContentLoaded", init);
