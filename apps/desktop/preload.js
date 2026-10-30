// Only the app's own start screen (a local file) gets access to the saved server address.
const { contextBridge, ipcRenderer } = require("electron");

if (window.location.protocol === "file:") {
  contextBridge.exposeInMainWorld("EcclesiaHost", {
    getServer: () => ipcRenderer.invoke("server:get"),
    setServer: (url) => ipcRenderer.invoke("server:set", url),
  });
}
