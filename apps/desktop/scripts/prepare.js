// Copies the shared launcher into ./launcher and writes its config.
// A church can ship a build that opens straight into its own server:
//   ECCLESIA_ADMIN_URL=https://admin.yourchurch.org npm run dist
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const dest = path.join(root, "launcher");
fs.rmSync(dest, { recursive: true, force: true });
fs.cpSync(path.join(root, "..", "launcher"), dest, { recursive: true });

const config = {
  appName: "Ecclesia Admin",
  expectedApp: "Ecclesia Admin",
  tagline: "Church management & finance",
  churchUrl: (process.env.ECCLESIA_ADMIN_URL || "").replace(/\/+$/, ""),
  vendor: "Pizza Technologies",
};
fs.writeFileSync(path.join(dest, "config.js"), "window.ECCLESIA_CONFIG = " + JSON.stringify(config, null, 2) + ";\n");
console.log("Prepared launcher/" + (config.churchUrl ? " (opens " + config.churchUrl + ")" : " (asks for the server address on first launch)"));
