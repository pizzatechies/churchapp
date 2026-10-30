// Builds www/ from the shared launcher (../launcher) and writes www/config.js.
// A church can ship its own build that opens straight into its members app:
//   ECCLESIA_CONNECT_URL=https://members.yourchurch.org npm run sync
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const www = path.join(root, "www");
fs.rmSync(www, { recursive: true, force: true });
fs.cpSync(path.join(root, "..", "launcher"), www, { recursive: true });

const config = {
  appName: "Ecclesia Connect",
  expectedApp: "Ecclesia Connect",
  churchUrl: (process.env.ECCLESIA_CONNECT_URL || "").replace(/\/+$/, ""),
  vendor: "Pizza Technologies",
};
fs.writeFileSync(path.join(www, "config.js"), "window.ECCLESIA_CONFIG = " + JSON.stringify(config, null, 2) + ";\n");
console.log("Prepared www/" + (config.churchUrl ? " (opens " + config.churchUrl + ")" : " (asks for the church address on first launch)"));
