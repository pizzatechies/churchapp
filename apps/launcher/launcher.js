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

  // Free hosting (such as Render's free plan) puts idle servers to sleep; waking one takes
  // about a minute, during which the host answers 502/503/504 or a holding page.
  var WAKE_LIMIT_MS = 120000;
  var ATTEMPT_MS = 20000;
  var RETRY_DELAY_MS = 3000;
  var SLOW_AFTER_MS = 4000;

  function failure(kind) {
    var err = new Error(kind);
    err.kind = kind;
    return err;
  }

  function checkOnce(url) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, ATTEMPT_MS);
    return fetch(url + "/healthz/", { cache: "no-store", signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) {
        if (r.status >= 500 || r.status === 429) throw failure("waking");
        if (!r.ok) throw failure("bad");
        if ((r.headers.get("content-type") || "").indexOf("json") === -1) throw failure("holding-page");
        return r.json();
      })
      .then(function (data) {
        clearTimeout(timer);
        if (!data || data.product !== "Ecclesia") throw failure("bad");
        return data;
      }, function (err) {
        clearTimeout(timer);
        throw err && err.kind ? err : failure("offline");
      });
  }

  // Keeps trying while the server wakes up, for up to two minutes. Calls onSlow once if it
  // takes longer than a few seconds. The returned promise has cancel().
  function check(url, onSlow) {
    var startedAt = Date.now();
    var cancelled = false;
    var rejectNow;
    var slowTimer = setTimeout(function () { if (onSlow) onSlow(); }, SLOW_AFTER_MS);
    var promise = new Promise(function (resolve, reject) {
      rejectNow = reject;
      (function attempt() {
        checkOnce(url).then(function (data) {
          if (!cancelled) resolve(data);
        }, function (err) {
          if (cancelled) return;
          if (err.kind !== "bad" && Date.now() - startedAt < WAKE_LIMIT_MS) setTimeout(attempt, RETRY_DELAY_MS);
          else reject(err);
        });
      })();
    });
    var stop = function () { clearTimeout(slowTimer); };
    promise.then(stop, stop);
    promise.cancel = function () {
      cancelled = true;
      stop();
      rejectNow(failure("cancelled"));
    };
    return promise;
  }

  var PANELS = ["connect", "confirm", "waking", "offline"];
  var wakingTimer = null;

  function show(id) {
    PANELS.forEach(function (p) { $(p).hidden = p !== id; });
    $("bar").classList.toggle("done", id !== "waking");
    if (id !== "waking") clearInterval(wakingTimer);
  }

  // The "Waking up" panel, with a running count so people can see it is still trying.
  function showWaking(url) {
    var since = Date.now();
    $("waking-text").textContent = "Trying " + url.replace(/^https?:\/\//, "") + ". After a quiet spell this can take up to a minute. Please keep the app open.";
    $("waking-time").textContent = "";
    show("waking");
    clearInterval(wakingTimer);
    wakingTimer = setInterval(function () {
      $("waking-time").textContent = "Still trying… " + Math.round((Date.now() - since) / 1000) + " seconds";
    }, 1000);
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
  var current = null;   // the check in progress, so Cancel can stop it
  var cancelTo = null;  // what Cancel goes back to

  function describe(err) {
    if (err.kind === "wrong") return err.message;
    if (err.kind === "bad" || err.kind === "holding-page") return "That address isn't an Ecclesia server. Please check it with your church office.";
    if (err.kind === "waking") return "Your church's server didn't finish starting. Please try again in a minute.";
    return "We couldn't reach that address. Check it, and your internet connection.";
  }

  $("connect-form").addEventListener("submit", function (e) {
    e.preventDefault();
    $("error").hidden = true;
    var url;
    try { url = normalize($("url").value); } catch (err) { showError(err.message || "That doesn't look like a web address."); return; }
    var btn = $("connect-btn");
    btn.disabled = true;
    btn.textContent = "Checking…";
    cancelTo = "connect";
    current = check(url, function () { showWaking(url); });
    current.then(function (data) {
      if (cfg.expectedApp && data.app !== cfg.expectedApp) {
        var other = data.app === "Ecclesia Admin" ? "the staff app (Ecclesia Admin)" : "the members app (Ecclesia Connect)";
        throw Object.assign(new Error("That address is for " + other + ". Ask your church for the " + cfg.expectedApp + " address."), { kind: "wrong" });
      }
      pending = url;
      $("confirm-title").textContent = "Connect to " + (data.church || "your church") + "?";
      $("confirm-url").textContent = url.replace(/^https?:\/\//, "");
      show("confirm");
    }).catch(function (err) {
      if (err.kind === "cancelled") return;
      show("connect");
      showError(describe(err));
    }).then(function () {
      btn.disabled = false;
      btn.textContent = "Continue";
    });
  });

  $("waking-cancel").addEventListener("click", function () {
    if (current) current.cancel();
    if (cancelTo === "offline") showOffline(currentUrl);
    else show("connect");
  });

  $("confirm-yes").addEventListener("click", function () {
    save(pending).then(function () { open(pending); });
  });
  $("confirm-no").addEventListener("click", function () { show("connect"); $("url").focus(); });
  $("retry").addEventListener("click", function () { start(); });
  $("change").addEventListener("click", function () { show("connect"); });

  var currentUrl = null;

  function showOffline(url) {
    $("offline-text").textContent = "We couldn't reach " + url.replace(/^https?:\/\//, "") + ". Check your internet connection and try again.";
    $("change").hidden = !!cfg.churchUrl;
    show("offline");
  }

  function start() {
    $("bar").classList.remove("done");
    PANELS.forEach(function (p) { $(p).hidden = true; });
    getSaved().then(function (saved) {
      var changing = window.location.hash === "#change" && !cfg.churchUrl;
      if (saved && !changing) {
        currentUrl = saved;
        cancelTo = "offline";
        current = check(saved, function () { showWaking(saved); });
        current.then(function () {
          // Save before opening: the desktop app only shows pages from the saved server,
          // and an address built into the app hasn't been saved yet.
          return save(saved).then(function () { afterSplash(function () { open(saved); }); });
        }).catch(function (err) {
            if (err.kind === "cancelled") return;
            afterSplash(function () { showOffline(saved); });
          });
      } else {
        if (saved) $("url").value = saved.replace(/^https?:\/\//, "");
        afterSplash(function () { show("connect"); });
      }
    });
  }

  start();
})();
