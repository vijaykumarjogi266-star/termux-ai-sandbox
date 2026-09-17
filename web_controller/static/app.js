/**
 * Antigravity AI Studio Frontend Controller
 * Modern AI Application UI with Multi-format Inputs, File Drop, and Live Log Streaming
 */

// DOM Elements
const promptInput = document.getElementById("prompt-input");
const jsonInput = document.getElementById("json-input");
const fileInput = document.getElementById("file-input");
const fileUploaderBox = document.getElementById("file-uploader-box");
const dropZone = document.getElementById("drop-zone");
const modelSelect = document.getElementById("model-select");
const modeSelect = document.getElementById("mode-select");

const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const clearPromptBtn = document.getElementById("clear-prompt-btn");

const charCount = document.getElementById("char-count");
const statusBadge = document.getElementById("status-badge");
const statusLabel = document.getElementById("status-label");

const metaTaskId = document.getElementById("meta-task-id");
const metaDuration = document.getElementById("meta-duration");
const metaExitCode = document.getElementById("meta-exit-code");

const outputConsole = document.getElementById("output-console");
const autoscrollToggle = document.getElementById("autoscroll-toggle");
const copyBtn = document.getElementById("copy-btn");
const downloadBtn = document.getElementById("download-btn");
const clearBtn = document.getElementById("clear-btn");

const connectionStatus = document.getElementById("connection-status");
const connectionText = document.getElementById("connection-text");
const themeToggle = document.getElementById("theme-toggle");

// State
let pollIntervalId = null;
let currentOffset = 0;
let isPolling = false;
let activeTab = "prompt-tab";

// Helper: Connection State
function setConnectionState(connected, message = "Connected") {
  if (connected) {
    connectionStatus.className = "status-dot dot-green";
    connectionText.textContent = message;
  } else {
    connectionStatus.className = "status-dot dot-red";
    connectionText.textContent = message;
  }
}

// Helper: Status Badge
function updateStatusBadge(status) {
  const normStatus = (status || "idle").toLowerCase();
  statusBadge.className = `status-badge status-${normStatus}`;
  statusLabel.textContent = normStatus.toUpperCase();
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
    jsonInput.disabled = true;
  } else {
    startBtn.disabled = false;
    stopBtn.disabled = true;
    promptInput.disabled = false;
    jsonInput.disabled = false;
  }
}

// Theme Toggle
themeToggle.addEventListener("click", () => {
  const html = document.documentElement;
  const currentTheme = html.getAttribute("data-theme");
  const nextTheme = currentTheme === "light" ? "dark" : "light";
  html.setAttribute("data-theme", nextTheme);
  themeToggle.querySelector(".theme-icon").textContent = nextTheme === "light" ? "☀️" : "🌙";
});

// Tab Switching
document.querySelectorAll(".tab-button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
    
    btn.classList.add("active");
    activeTab = btn.getAttribute("data-tab");
    document.getElementById(activeTab).classList.add("active");
  });
});

// Preset Chips Handling
document.querySelectorAll(".preset-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const promptText = chip.getAttribute("data-prompt");
    promptInput.value = promptText;
    updateCharCount();
    
    // Switch to Prompt Tab
    document.querySelector('[data-tab="prompt-tab"]').click();
    promptInput.focus();
  });
});

// Character Counter
function updateCharCount() {
  const text = getActivePromptText();
  charCount.textContent = `${text.length.toLocaleString()} characters`;
}

promptInput.addEventListener("input", updateCharCount);
jsonInput.addEventListener("input", updateCharCount);

function getActivePromptText() {
  if (activeTab === "json-tab") {
    try {
      const parsed = JSON.parse(jsonInput.value.trim());
      return parsed.prompt || jsonInput.value.trim();
    } catch {
      return jsonInput.value.trim();
    }
  }
  return promptInput.value.trim();
}

// Keyboard Shortcut: Ctrl + Enter
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    if (!startBtn.disabled) {
      startTask();
    }
  }
});

// Drag and Drop File Handling
if (dropZone) {
  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropZone.classList.add("drag-over");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropZone.classList.remove("drag-over");
    });
  });

  dropZone.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      readFileIntoPrompt(files[0]);
    }
  });
}

// File Input Picker
fileInput.addEventListener("change", (e) => {
  if (e.target.files.length > 0) {
    readFileIntoPrompt(e.target.files[0]);
  }
});

function readFileIntoPrompt(file) {
  const reader = new FileReader();
  reader.onload = (e) => {
    promptInput.value = e.target.result;
    updateCharCount();
    
    // Update file details display
    document.getElementById("file-name").textContent = file.name;
    document.getElementById("file-size").textContent = `${(file.size / 1024).toFixed(1)} KB`;
    document.getElementById("file-details").classList.remove("hidden");
    
    // Switch to prompt tab
    document.querySelector('[data-tab="prompt-tab"]').click();
  };
  reader.readAsText(file);
}

// Clear Prompt
clearPromptBtn.addEventListener("click", () => {
  promptInput.value = "";
  jsonInput.value = "";
  updateCharCount();
});

// Console Action Toolbar
clearBtn.addEventListener("click", () => {
  outputConsole.textContent = "";
});

copyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(outputConsole.textContent);
    const origHTML = copyBtn.innerHTML;
    copyBtn.innerHTML = "<span>✓</span> Copied!";
    setTimeout(() => { copyBtn.innerHTML = origHTML; }, 1500);
  } catch (err) {
    alert("Copy failed: " + err.message);
  }
});

downloadBtn.addEventListener("click", () => {
  const text = outputConsole.textContent;
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `agy_execution_log_${Date.now()}.txt`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
});

// Polling Status & Incremental Output
async function pollTaskStatus() {
  if (isPolling) return;
  isPolling = true;

  try {
    const res = await fetch(`/api/task/status?offset=${currentOffset}`);
    if (!res.ok) throw new Error(`Status check HTTP ${res.status}`);
    
    const data = await res.json();
    setConnectionState(true, "Connected");

    if (data.hasTask) {
      updateStatusBadge(data.status);
      metaTaskId.textContent = data.taskId || "—";
      metaDuration.textContent = `${(data.duration || 0).toFixed(1)}s`;
      metaExitCode.textContent = data.exitCode !== null && data.exitCode !== undefined ? data.exitCode : "—";

      if (data.output && data.output.length > 0) {
        if (currentOffset === 0) {
          outputConsole.textContent = data.output;
        } else {
          outputConsole.textContent += data.output;
        }
        currentOffset = data.offset;
        scrollToBottomIfNeeded();
      }

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

// Start Task Execution
async function startTask() {
  const prompt = getActivePromptText();
  if (!prompt) {
    alert("Please enter a prompt instruction or upload a task file.");
    promptInput.focus();
    return;
  }

  const model = modelSelect.value || undefined;
  const mode = modeSelect.value || undefined;

  currentOffset = 0;
  outputConsole.textContent = `[Initiating AI task execution with AGY CLI...]\n`;
  updateStatusBadge("running");
  setActionButtonsRunning(true);
  
  metaTaskId.textContent = "starting...";
  metaDuration.textContent = "0.0s";
  metaExitCode.textContent = "—";

  try {
    const res = await fetch("/api/task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, model, mode }),
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

// Stop Task Execution
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

startBtn.addEventListener("click", startTask);
stopBtn.addEventListener("click", stopTask);

// Initial Health Check
async function init() {
  try {
    const res = await fetch("/api/health");
    if (res.ok) {
      const data = await res.json();
      setConnectionState(true, "Connected");
      pollTaskStatus();
    } else {
      setConnectionState(false, "Server Error");
    }
  } catch (err) {
    setConnectionState(false, "Offline");
  }
}

window.addEventListener("DOMContentLoaded", init);
