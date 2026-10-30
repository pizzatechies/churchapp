/*
 * Ecclesia app launcher (shared by the mobile and desktop apps).
 * Shows the brand splash, then opens the church's Ecclesia server. On first launch it asks
 * for the address and checks it is a real Ecclesia server of the expected kind.
 */
(function () {
  "use strict";
  var cfg = window.ECCLESIA_CONFIG || {};
  var KEY = "ecclesia.serverUrl." + (cfg.expectedApp || "app");
  var MIN_SPLASH_MS = 1200;
  var started = Date.now();
  var $ = function (id) { return document.getElementById(id); };
  var host = window.EcclesiaHost || null; // provided by the desktop app

  $("app-name").textContent = cfg.appName || "Ecclesia";
  document.title = cfg.appName || "Ecclesia";
  $("app-tag").textContent = cfg.tagline || (cfg.expectedApp === "Ecclesia Admin" ? "Church management & finance" : "Fellowships, groups & sermons");
  if (cfg.expectedApp === "Ecclesia Admin") {
    $("connect-hint").textContent = "Enter your church's Ecclesia Admin address (for church staff).";
    $("url").placeholder = "admin.yourchurch.org";
  }

  function getSaved() {
    if (cfg.churchUrl) return Promise.resolve(cfg.churchUrl);
    if (host && host.getServer) return host.getServer();
    try { return Promise.resolve(localStorage.getItem(KEY)); } catch (e) { return Promise.resolve(null); }
  }
  function save(url) {
    if (host && host.setServer) return host.setServer(url);
    try { localStorage.setItem(KEY, url); } catch (e) {}
    return Promise.resolve();
  }

  function normalize(input) {
    var url = String(input || "").trim();
    if (!url) throw new Error("Please enter your church's address.");
    if (!/^https?:\/\//i.test(url)) url = "https://" + url;
    var parsed = new URL(url);
    return (parsed.origin + parsed.pathname).replace(/\/+$/, "");
  }

  function check(url) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 12000);
    return fetch(url + "/healthz/", { cache: "no-store", signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) {
        clearTimeout(timer);
        if (!r.ok) throw Object.assign(new Error("status"), { kind: "bad" });
        return r.json();
      })
      .then(function (data) {
        if (!data || data.product !== "Ecclesia") throw Object.assign(new Error("not ecclesia"), { kind: "bad" });
        return data;
      }, function (err) {
        clearTimeout(timer);
        if (err && err.kind) throw err;
        throw Object.assign(new Error("offline"), { kind: "offline" });
      });
  }

  function show(id) {
    ["connect", "confirm", "offline"].forEach(function (p) { $(p).hidden = p !== id; });
    $("bar").classList.add("done");
  }

  function afterSplash(fn) {
    var wait = Math.max(0, MIN_SPLASH_MS - (Date.now() - started));
    setTimeout(fn, wait);
  }

  function open(url) {
    window.location.replace(url + "/");
  }

  function showError(message) {
    $("error").textContent = message;
    $("error").hidden = false;
  }

  var pending = null;

  $("connect-form").addEventListener("submit", function (e) {
    e.preventDefault();
    $("error").hidden = true;
    var url;
    try { url = normalize($("url").value); } catch (err) { showError(err.message || "That doesn't look like a web address."); return; }
    var btn = $("connect-btn");
    btn.disabled = true;
    btn.textContent = "Checking…";
    check(url).then(function (data) {
      if (cfg.expectedApp && data.app !== cfg.expectedApp) {
        var other = data.app === "Ecclesia Admin" ? "the staff app (Ecclesia Admin)" : "the members app (Ecclesia Connect)";
        throw Object.assign(new Error("That address is for " + other + ". Ask your church for the " + cfg.expectedApp + " address."), { kind: "wrong" });
      }
      pending = url;
      $("confirm-title").textContent = "Connect to " + (data.church || "your church") + "?";
      $("confirm-url").textContent = url.replace(/^https?:\/\//, "");
      show("confirm");
    }).catch(function (err) {
      if (err.kind === "wrong") showError(err.message);
      else if (err.kind === "offline") showError("We couldn't reach that address. Check it, and your internet connection.");
      else showError("That address isn't an Ecclesia server. Please check it with your church office.");
    }).then(function () {
      btn.disabled = false;
      btn.textContent = "Continue";
    });
  });

  $("confirm-yes").addEventListener("click", function () {
    save(pending).then(function () { open(pending); });
  });
  $("confirm-no").addEventListener("click", function () { show("connect"); $("url").focus(); });
  $("retry").addEventListener("click", function () { start(); });
  $("change").addEventListener("click", function () { show("connect"); });

  function start() {
    $("bar").classList.remove("done");
    ["connect", "confirm", "offline"].forEach(function (p) { $(p).hidden = true; });
    getSaved().then(function (saved) {
      var changing = window.location.hash === "#change" && !cfg.churchUrl;
      if (saved && !changing) {
        check(saved).then(function () { afterSplash(function () { open(saved); }); })
          .catch(function () {
            afterSplash(function () {
              $("offline-text").textContent = "We couldn't reach " + saved.replace(/^https?:\/\//, "") + ". Check your internet connection and try again.";
              $("change").hidden = !!cfg.churchUrl;
              show("offline");
            });
          });
      } else {
        if (saved) $("url").value = saved.replace(/^https?:\/\//, "");
        afterSplash(function () { show("connect"); });
      }
    });
  }

  start();
})();
