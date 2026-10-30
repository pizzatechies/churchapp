(function () {
  "use strict";

  var cfg = window.ECCLESIA_SITE || {};
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var money = function (n) { return (cfg.currency || "KSh") + " " + Math.round(n).toLocaleString("en-KE"); };

  // ------------------------------------------------------------------ navigation
  var toggle = $(".nav-toggle");
  var links = $("#nav-links");
  toggle.addEventListener("click", function () {
    var open = links.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  });
  $$("a", links).forEach(function (a) {
    a.addEventListener("click", function () {
      links.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
    });
  });
  $$("[data-year]").forEach(function (el) { el.textContent = new Date().getFullYear(); });

  // ------------------------------------------------------------------ interactive demo
  var tour = $("[data-tour]");
  var steps = window.ECCLESIA_TOUR || {};
  var shots = window.ECCLESIA_SHOTS || {};
  var SIZES = { admin: [1920, 1200], connect: [780, 1688] };
  var state = { app: "admin", index: 0, timer: null };

  function stopsFor(app) {
    return (steps[app] || []).filter(function (s) { return shots[app] && shots[app][s.id]; });
  }

  function renderSteps() {
    var list = $("[data-tour-steps]", tour);
    list.innerHTML = "";
    stopsFor(state.app).forEach(function (stop, i) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.innerHTML = "<span class=\"n\">" + (i + 1) + "</span><span class=\"t\"></span>";
      btn.querySelector(".t").textContent = stop.title;
      btn.addEventListener("click", function () { pause(); show(i); });
      li.appendChild(btn);
      list.appendChild(li);
    });
  }

  function show(i) {
    var stops = stopsFor(state.app);
    if (!stops.length) return;
    state.index = (i + stops.length) % stops.length;
    var stop = stops[state.index];
    var shot = shots[state.app][stop.id];
    var img = $("[data-tour-img]", tour);
    var spot = $("[data-tour-spot]", tour);
    var size = SIZES[state.app];

    spot.classList.remove("is-on");
    img.width = size[0];
    img.height = size[1];
    img.alt = stop.title + ": " + stop.text;
    $("[data-tour-zoom]", tour).href = shot.src;
    var place = function () {
      var s = shot.spot;
      if (!s) return;
      var pad = state.app === "admin" ? 0.6 : 1.2;
      spot.style.left = Math.max(0, s.x - pad) + "%";
      spot.style.top = Math.max(0, s.y - pad * 0.8) + "%";
      spot.style.width = Math.min(100, s.w + pad * 2) + "%";
      spot.style.height = Math.min(100, s.h + pad * 1.6) + "%";
      // Restart the pulse so the eye is drawn to it on every stop.
      void spot.offsetWidth;
      spot.classList.add("is-on");
    };
    // Replace the handler every time, so a slow earlier screen can't move the highlight.
    img.onload = place;
    img.src = shot.src;
    if (img.complete) place();

    $("[data-tour-count]", tour).textContent = "Stop " + (state.index + 1) + " of " + stops.length;
    $("[data-tour-title]", tour).textContent = stop.title;
    $("[data-tour-text]", tour).textContent = stop.text;
    $$("[data-tour-steps] button", tour).forEach(function (b, n) {
      if (n === state.index) {
        b.setAttribute("aria-current", "step");
        if (b.scrollIntoView && b.parentNode.parentNode.scrollWidth > b.parentNode.parentNode.clientWidth) {
          b.parentNode.parentNode.scrollTo({ left: b.parentNode.offsetLeft - 16, behavior: "smooth" });
        }
      } else {
        b.removeAttribute("aria-current");
      }
    });
    // Load the next screen ahead of time.
    var next = stops[(state.index + 1) % stops.length];
    if (next) (new Image()).src = shots[state.app][next.id].src;
  }

  function setApp(app) {
    state.app = app;
    tour.setAttribute("data-app", app);
    $$("[data-tour-app]", tour).forEach(function (b) {
      b.setAttribute("aria-selected", b.getAttribute("data-tour-app") === app ? "true" : "false");
    });
    var device = $("[data-tour-device]", tour);
    device.classList.toggle("is-phone", app === "connect");
    $("[data-tour-address]", tour).textContent = app === "connect" ? "members.yourchurch.org" : "admin.yourchurch.org";
    renderSteps();
    show(0);
  }

  function play() {
    var btn = $("[data-tour-play]", tour);
    btn.innerHTML = "<i class=\"bi bi-pause-fill\"></i> <span>Pause</span>";
    state.timer = setInterval(function () {
      var stops = stopsFor(state.app);
      if (state.index + 1 < stops.length) {
        show(state.index + 1);
      } else if (state.app === "admin") {
        setApp("connect");
      } else {
        pause();
      }
    }, 6000);
  }

  function pause() {
    clearInterval(state.timer);
    state.timer = null;
    $("[data-tour-play]", tour).innerHTML = "<i class=\"bi bi-play-fill\"></i> <span>Play</span>";
  }

  if (tour) {
    $$("[data-tour-app]", tour).forEach(function (b) {
      b.addEventListener("click", function () { pause(); setApp(b.getAttribute("data-tour-app")); });
    });
    $("[data-tour-prev]", tour).addEventListener("click", function () { pause(); show(state.index - 1); });
    $("[data-tour-next]", tour).addEventListener("click", function () { pause(); show(state.index + 1); });
    $("[data-tour-play]", tour).addEventListener("click", function () { if (state.timer) pause(); else play(); });
    tour.addEventListener("keydown", function (e) {
      if (e.target.closest("input, textarea, select")) return;
      if (e.key === "ArrowRight") { pause(); show(state.index + 1); }
      if (e.key === "ArrowLeft") { pause(); show(state.index - 1); }
    });
    // Swipe between stops on touch screens.
    var startX = null;
    var screen = $(".tour-screen", tour);
    screen.addEventListener("touchstart", function (e) { startX = e.touches[0].clientX; }, { passive: true });
    screen.addEventListener("touchend", function (e) {
      if (startX === null) return;
      var dx = e.changedTouches[0].clientX - startX;
      if (Math.abs(dx) > 40) { pause(); show(state.index + (dx < 0 ? 1 : -1)); }
      startX = null;
    });
    setApp("admin");
  }

  // Live demo server, when there is one.
  var live = cfg.liveDemo || {};
  if (live.admin || live.members) {
    var box = $("[data-live-demo]");
    box.hidden = false;
    [["admin", "[data-live-admin]"], ["members", "[data-live-members]"]].forEach(function (pair) {
      var a = $(pair[1], box);
      if (live[pair[0]]) a.href = live[pair[0]]; else a.hidden = true;
    });
  }

  // ------------------------------------------------------------------ downloads
  var downloads = cfg.downloads || {};
  $$("[data-download]").forEach(function (a) {
    var url = downloads[a.getAttribute("data-download")];
    var badge = $("em", a);
    if (url) {
      a.href = url;
      a.rel = "noopener";
      badge.innerHTML = "<i class=\"bi bi-download\"></i>";
    } else {
      a.classList.add("is-soon");
      a.setAttribute("aria-disabled", "true");
      badge.textContent = "Coming soon";
    }
  });

  // ------------------------------------------------------------------ pricing
  var prices = cfg.prices || {};
  var months = cfg.yearlyMonths || 12;
  var billing = "monthly";
  var chip = $("[data-save-chip]");
  if (months < 12) chip.textContent = (12 - months) + (12 - months === 1 ? " month" : " months") + " free";
  else chip.hidden = true;

  function renderPrices() {
    $$("[data-plan]").forEach(function (card) {
      var monthly = prices[card.getAttribute("data-plan")];
      if (!monthly) return;
      var yearly = monthly * months;
      if (billing === "monthly") {
        $("[data-price]", card).textContent = money(monthly);
        $("[data-period]", card).textContent = "/month";
        $("[data-price-note]", card).textContent = "or " + money(yearly) + " a year";
      } else {
        $("[data-price]", card).textContent = money(yearly);
        $("[data-period]", card).textContent = "/year";
        $("[data-price-note]", card).textContent = months < 12
          ? "Works out at " + money(yearly / 12) + " a month. You save " + money(monthly * 12 - yearly) + "."
          : "Works out at " + money(monthly) + " a month.";
      }
    });
    $$("[data-billing]").forEach(function (b) {
      b.setAttribute("aria-checked", b.getAttribute("data-billing") === billing ? "true" : "false");
    });
  }
  $$("[data-billing]").forEach(function (b) {
    b.addEventListener("click", function () { billing = b.getAttribute("data-billing"); renderPrices(); });
  });
  renderPrices();

  // ------------------------------------------------------------------ get started
  var form = $("[data-contact-form]");
  var contact = cfg.contact || {};
  $$("[data-choose-plan]").forEach(function (a) {
    a.addEventListener("click", function () {
      form.elements.plan.value = a.getAttribute("data-choose-plan");
      form.elements.billing.value = billing === "yearly" ? "Yearly" : "Monthly";
    });
  });

  var direct = $("[data-contact-direct]");
  function addDirect(icon, label, href) {
    var li = document.createElement("li");
    li.innerHTML = "<i class=\"bi " + icon + "\"></i> <a></a>";
    $("a", li).textContent = label;
    $("a", li).href = href;
    direct.appendChild(li);
  }
  if (contact.phone) addDirect("bi-telephone", contact.phone, "tel:" + contact.phone.replace(/[^\d+]/g, ""));
  if (contact.whatsapp) addDirect("bi-whatsapp", "WhatsApp us", "https://wa.me/" + contact.whatsapp);
  if (contact.email) addDirect("bi-envelope", contact.email, "mailto:" + contact.email);

  var sendWhatsapp = $("[data-send=whatsapp]", form);
  var sendEmail = $("[data-send=email]", form);
  sendWhatsapp.hidden = !contact.whatsapp;
  sendEmail.hidden = !contact.email;
  // When email is the only way to send, it gets the main button style.
  if (!contact.whatsapp) sendEmail.className = "btn btn-gold";
  var note = $("[data-form-note]", form);
  if (!contact.whatsapp && !contact.email) {
    $("[data-contact-actions]", form).hidden = true;
    note.hidden = false;
    note.textContent = "Online enquiries open soon.";
    if (window.console) console.warn("Ecclesia website: set contact.email or contact.whatsapp in js/config.js");
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!form.reportValidity()) return;
    var f = form.elements;
    var lines = [
      "Hello, we'd like to bring Ecclesia to our church.",
      "",
      "Name: " + f.name.value.trim(),
      "Church: " + f.church.value.trim(),
      f.phone.value.trim() ? "Phone: " + f.phone.value.trim() : "",
      f.email.value.trim() ? "Email: " + f.email.value.trim() : "",
      "Plan: " + f.plan.value + " (" + f.billing.value.toLowerCase() + ")",
      f.message.value.trim() ? "\n" + f.message.value.trim() : "",
    ].filter(function (line, i) { return line !== "" || i === 1; });
    var text = lines.join("\n");
    var via = e.submitter ? e.submitter.getAttribute("data-send") : (contact.whatsapp ? "whatsapp" : "email");
    if (via === "whatsapp" && contact.whatsapp) {
      window.open("https://wa.me/" + contact.whatsapp + "?text=" + encodeURIComponent(text), "_blank", "noopener");
    } else if (contact.email) {
      window.location.href = "mailto:" + contact.email + "?subject=" + encodeURIComponent("Ecclesia for " + f.church.value.trim())
        + "&body=" + encodeURIComponent(text);
    }
    note.hidden = false;
    // The app may not open (for example inside some in-app browsers), so always give the address too.
    note.textContent = (via === "whatsapp" ? "WhatsApp" : "Your email app") + " should open with your message ready to send. If it doesn't, contact us at "
      + (via === "whatsapp" ? "+" + contact.whatsapp : contact.email) + ".";
  });
})();
