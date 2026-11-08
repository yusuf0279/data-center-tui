// My Data Center - VS Code extension.
// The game itself lives in media/ (a copy of ../web, see scripts/build.mjs) and runs in a
// webview. This file only hosts it: it persists the save in VS Code's own storage and
// mirrors your balance and income into the status bar.
const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const SAVE_KEY = "dataCenter.save";
let panel;
let status;

function activate(context) {
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  status.command = "dataCenter.open";
  resetStatus();
  status.show();
  context.subscriptions.push(
    status,
    vscode.commands.registerCommand("dataCenter.open", () => openPanel(context))
  );
}

function resetStatus() {
  status.text = "$(server) Data Center";
  status.tooltip = "Play My Data Center";
  status.backgroundColor = undefined;
}

function showStatus(s) {
  if (!s || typeof s !== "object") return;
  status.text = `$(server) $${s.balance} · +$${s.income}/s`;
  status.tooltip = `${s.site}\nClick to open My Data Center`;
  status.backgroundColor = s.crisis
    ? new vscode.ThemeColor("statusBarItem.errorBackground")
    : undefined;
}

function openPanel(context) {
  if (panel) {
    panel.reveal();
    return;
  }
  const media = vscode.Uri.joinPath(context.extensionUri, "media");
  panel = vscode.window.createWebviewPanel(
    "dataCenter",
    "My Data Center",
    vscode.ViewColumn.Beside,
    {
      enableScripts: true,
      retainContextWhenHidden: true, // keep ticking while the tab is in the background
      localResourceRoots: [media],
    }
  );
  panel.webview.html = buildHtml(panel.webview, media);

  panel.webview.onDidReceiveMessage(
    (msg) => {
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "load") {
        panel.webview.postMessage({
          type: "loaded",
          json: context.globalState.get(SAVE_KEY) || null,
        });
      } else if (msg.type === "save" && typeof msg.json === "string") {
        context.globalState.update(SAVE_KEY, msg.json);
      } else if (msg.type === "status") {
        showStatus(msg.status);
      }
    },
    undefined,
    context.subscriptions
  );
  panel.onDidDispose(
    () => {
      panel = undefined;
      resetStatus();
    },
    undefined,
    context.subscriptions
  );
}

// Takes the game's own index.html, points its local files at webview URIs, adds a
// strict CSP, and injects the host bridge before the first script runs.
function buildHtml(webview, media) {
  const nonce = crypto.randomBytes(16).toString("base64");
  const file = path.join(media.fsPath, "index.html");
  let html;
  try {
    html = fs.readFileSync(file, "utf8");
  } catch {
    return `<!doctype html><body style="font-family:sans-serif;padding:2em">
      Game files are missing (media/index.html). Run <code>npm run build</code> in the repository.</body>`;
  }
  const uri = (name) => webview.asWebviewUri(vscode.Uri.joinPath(media, name)).toString();
  html = html.replace(/(src|href)="(?!https?:|data:|#)([^"]+)"/g, (_, attr, name) =>
    attr === "src" ? `src="${uri(name)}" nonce="${nonce}"` : `href="${uri(name)}"`
  );
  const csp =
    `default-src 'none'; img-src ${webview.cspSource} data:; ` +
    `style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';`;
  const bridge = `<script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    let waiting = null;
    window.addEventListener("message", (e) => {
      if (e.data && e.data.type === "loaded" && waiting) { waiting(e.data.json); waiting = null; }
    });
    window.DC_HOST = {
      theme: "vscode",
      storage: {
        load: () => new Promise((resolve) => { waiting = resolve; vscode.postMessage({ type: "load" }); }),
        save: (json) => vscode.postMessage({ type: "save", json }),
      },
      onStatus: (status) => vscode.postMessage({ type: "status", status }),
    };
  </script>`;
  const meta = `<meta http-equiv="Content-Security-Policy" content="${csp}">`;
  html = html.replace(/<head[^>]*>/i, (m) => `${m}\n${meta}`);
  // the bridge must run before the game's own scripts
  const first = html.search(/<script[\s>]/i);
  return first === -1 ? html + bridge : html.slice(0, first) + bridge + "\n" + html.slice(first);
}

function deactivate() {}

module.exports = { activate, deactivate, buildHtml };
