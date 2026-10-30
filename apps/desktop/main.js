/*
 * Ecclesia Admin for Windows, macOS and Linux.
 *
 * A secure desktop shell around the church's Ecclesia Admin server: it remembers the
 * server address, keeps navigation on that server, opens other links in the browser,
 * and adds native menus, printing and downloads.
 */
const { app, BrowserWindow, Menu, dialog, ipcMain, session, shell } = require("electron");
const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");

const APP_NAME = "Ecclesia Admin";
const SITE = "https://ecclesia.pizzatechnologies.example";
const LAUNCHER = path.join(__dirname, "launcher", "index.html");
const LAUNCHER_DIR_URL = pathToFileURL(path.join(__dirname, "launcher")).href + "/";
const SETTINGS = () => path.join(app.getPath("userData"), "settings.json");

app.setName(APP_NAME);

function readSettings() {
  try {
    return JSON.parse(fs.readFileSync(SETTINGS(), "utf8"));
  } catch {
    return {};
  }
}

function writeSettings(values) {
  const merged = { ...readSettings(), ...values };
  fs.mkdirSync(path.dirname(SETTINGS()), { recursive: true });
  fs.writeFileSync(SETTINGS(), JSON.stringify(merged, null, 2));
}

function serverOrigin() {
  const server = readSettings().server;
  try {
    return server ? new URL(server).origin : null;
  } catch {
    return null;
  }
}

function isAllowed(url) {
  if (url.startsWith("file:")) return url.startsWith(LAUNCHER_DIR_URL);
  const origin = serverOrigin();
  try {
    return origin !== null && new URL(url).origin === origin;
  } catch {
    return false;
  }
}

let win = null;

function showLauncher(change = false) {
  if (!win) return;
  win.loadFile(LAUNCHER, change ? { hash: "change" } : undefined);
}

function createWindow() {
  const state = readSettings().window || {};
  win = new BrowserWindow({
    width: state.width || 1360,
    height: state.height || 900,
    x: state.x,
    y: state.y,
    minWidth: 980,
    minHeight: 640,
    backgroundColor: "#0b1d51",
    title: APP_NAME,
    icon: path.join(__dirname, "build", "icon.png"),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: true,
    },
  });
  if (state.maximized) win.maximize();
  win.once("ready-to-show", () => win.show());

  // Identify the desktop app to the server (skips the web splash, which the app already showed).
  win.webContents.setUserAgent(win.webContents.getUserAgent() + " EcclesiaApp/1.0 (Desktop)");

  // Keep navigation on the church's server; everything else opens in the default browser.
  win.webContents.on("will-navigate", (event, url) => {
    if (!isAllowed(url)) {
      event.preventDefault();
      if (/^https?:/.test(url)) shell.openExternal(url);
    }
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowed(url)) {
      win.loadURL(url);
    } else if (/^https?:/.test(url)) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });

  // If the server can't be reached, go back to the start screen, which explains and offers a retry.
  win.webContents.on("did-fail-load", (_event, code, _desc, url, isMainFrame) => {
    if (isMainFrame && code !== -3 && !url.startsWith("file://")) showLauncher();
  });

  win.on("close", () => {
    const bounds = win.getNormalBounds();
    writeSettings({ window: { ...bounds, maximized: win.isMaximized() } });
  });
  win.on("closed", () => {
    win = null;
  });

  showLauncher();
}

ipcMain.handle("server:get", () => readSettings().server || null);
ipcMain.handle("server:set", (_event, url) => {
  const parsed = new URL(url);
  if (!/^https?:$/.test(parsed.protocol)) throw new Error("Only web addresses are allowed.");
  writeSettings({ server: parsed.origin + parsed.pathname.replace(/\/+$/, "") });
  return true;
});

function buildMenu() {
  const isMac = process.platform === "darwin";
  const template = [
    ...(isMac ? [{ role: "appMenu" }] : []),
    {
      label: "File",
      submenu: [
        { label: "Home", accelerator: "CmdOrCtrl+H", click: () => readSettings().server && win && win.loadURL(readSettings().server + "/") },
        { label: "Print…", accelerator: "CmdOrCtrl+P", click: () => win && win.webContents.print() },
        { type: "separator" },
        { label: "Change church server…", click: () => showLauncher(true) },
        { type: "separator" },
        isMac ? { role: "close" } : { role: "quit" },
      ],
    },
    { role: "editMenu" },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { label: "Back", accelerator: "Alt+Left", click: () => win && win.webContents.navigationHistory.canGoBack() && win.webContents.navigationHistory.goBack() },
        { label: "Forward", accelerator: "Alt+Right", click: () => win && win.webContents.navigationHistory.canGoForward() && win.webContents.navigationHistory.goForward() },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
        ...(app.isPackaged ? [] : [{ role: "toggleDevTools" }]),
      ],
    },
    { role: "windowMenu" },
    {
      label: "Help",
      submenu: [
        { label: "Ecclesia website", click: () => shell.openExternal(SITE) },
        {
          label: "About Ecclesia Admin",
          click: () =>
            dialog.showMessageBox(win, {
              type: "info",
              title: "About Ecclesia Admin",
              message: `${APP_NAME} ${app.getVersion()}`,
              detail: "Church management & finance.\nA product of Pizza Technologies.",
              icon: path.join(__dirname, "build", "icon.png"),
            }),
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(() => {
    // The admin app never needs the camera, microphone, location or notifications.
    session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
      callback(permission === "clipboard-sanitized-write" || permission === "fullscreen");
    });
    buildMenu();
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
