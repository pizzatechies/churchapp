#!/usr/bin/env node
/*
 * Regenerates the website's interactive demo: a screenshot of each tour stop in both
 * apps, plus where the highlighted element sits on it (js/tour-shots.js).
 *
 * 1. Run both apps with the sample church loaded (see the main README):
 *      python manage.py load_demo_data
 *      python manage.py runserver 8000
 *      DJANGO_SETTINGS_MODULE=config.settings_portal python manage.py runserver 8001
 * 2. cd website/tools && npm install && node capture-demo.cjs
 *
 * The words shown with each stop live in js/tour-steps.js.
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ADMIN = process.env.ADMIN_URL || "http://127.0.0.1:8000";
const MEMBERS = process.env.MEMBERS_URL || "http://127.0.0.1:8001";
const PASSWORD = process.env.DEMO_PASSWORD || "ChurchDemo-2026";
const MEMBER = process.env.DEMO_MEMBER || "eunice.gitau";
const SITE = path.resolve(__dirname, "..");
const OUT = path.join(SITE, "img", "demo");

// Each stop: the page, and the element to spotlight on it.
const ADMIN_STOPS = [
  { id: "dashboard", url: "/", spot: (p) => p.locator(".stat-card").first() },
  { id: "offering", url: firstLink("/giving/batches/", "/giving/batches/"), spot: (p) => p.locator(".card", { has: p.getByText("By method", { exact: true }) }).last() },
  { id: "approvals", url: "/expenses/approvals/", spot: (p) => p.getByRole("button", { name: "Approve" }).first() },
  { id: "payroll", url: firstLink("/payroll/", "/payroll/runs/", "/stub/"), spot: (p) => p.locator("tr", { hasText: "PAYE" }).first() },
  { id: "budget", url: "/reports/budget-vs-actual/", spot: (p) => p.locator("tr", { hasText: "Total income" }).first() },
  { id: "reports", url: "/reports/", spot: (p) => p.locator(".card").first() },
  { id: "congregation", url: "/congregation/summary/", spot: (p) => p.locator(".card", { has: p.getByText("By age group and gender") }).last() },
  { id: "groups", url: groupUrl("Women's Fellowship"), spot: (p) => p.locator(".card", { has: p.getByText("Induct members") }).last() },
  { id: "sermons", url: "/congregation/sermons/new/", spot: (p) => p.locator("input[type=file]").first() },
];

const CONNECT_STOPS = [
  { id: "home", url: "/", spot: (p) => p.locator(".portal-main .col-lg-7 .portal-list-item").first() },
  { id: "groups", url: "/groups/", spot: (p) => p.locator(".card").first() },
  { id: "group", url: groupUrl("Women's Fellowship", "/groups/"), spot: (p) => p.locator(".alert-success, .alert").first() },
  { id: "sermon", url: firstLink("/sermons/", "/sermons/"), spot: (p) => p.locator("audio, video, iframe").first() },
  { id: "profile", url: "/profile/", spot: (p) => p.locator("form.card .card-header").first() },
];

// The URL of the first link on a page whose path starts with `prefix` (and optionally a
// second hop, e.g. a payroll run's first pay stub), so the script survives new demo data.
function firstLink(listUrl, prefix, secondPrefix) {
  return async (page, base) => {
    await page.goto(base + listUrl);
    let href = await page.$$eval(`a[href^="${prefix}"]`, (as, listUrl) =>
      as.map((a) => a.getAttribute("href")).find((h) => /\d/.test(h) && h !== listUrl), listUrl);
    if (secondPrefix) {
      await page.goto(base + href);
      href = await page.$$eval("a", (as, s) => as.map((a) => a.getAttribute("href")).find((h) => h && h.endsWith(s)), secondPrefix);
    }
    return href;
  };
}

function groupUrl(name, prefix = "/congregation/groups/") {
  return async (page, base) => {
    await page.goto(base + prefix);
    return page.getByRole("link", { name, exact: true }).first().getAttribute("href");
  };
}

async function signIn(page, url, username) {
  await page.goto(url);
  await page.fill("#id_username", username);
  await page.fill("#id_password", PASSWORD);
  await Promise.all([page.waitForNavigation(), page.click("button[type=submit]")]);
}

async function shoot(context, base, stops, prefix, loginPath, username) {
  const page = await context.newPage();
  await signIn(page, base + loginPath, username);
  const shots = {};
  for (const stop of stops) {
    const url = typeof stop.url === "function" ? await stop.url(page, base) : stop.url;
    await page.goto(base + url);
    await page.waitForLoadState("networkidle");
    const spot = stop.spot(page);
    await spot.evaluate((el) => {
      // Bring tall elements to the top of the screen and small ones to the middle.
      const tall = el.getBoundingClientRect().height > window.innerHeight * 0.5;
      el.scrollIntoView({ block: tall ? "start" : "center", behavior: "instant" });
      if (tall && window.scrollY > 0) window.scrollBy({ top: -90, behavior: "instant" });
    });
    await page.waitForTimeout(400);
    const box = await spot.boundingBox();
    const view = page.viewportSize();
    const file = `${prefix}-${stop.id}.jpg`;
    await page.screenshot({ path: path.join(OUT, file), type: "jpeg", quality: 78 });
    const pct = (v, total) => Math.round((v / total) * 10000) / 100;
    // Keep the highlight on screen even when the element runs past the bottom.
    const top = Math.max(0, box.y);
    const bottom = Math.min(view.height, box.y + box.height);
    shots[stop.id] = {
      src: `img/demo/${file}`,
      spot: { x: pct(box.x, view.width), y: pct(top, view.height), w: pct(box.width, view.width), h: pct(bottom - top, view.height) },
    };
    console.log(`${prefix}/${stop.id}: ${url}`);
  }
  await page.close();
  return shots;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const skipSplash = () => {
    sessionStorage.setItem("splash-seen-ecclesia-admin", "1");
    sessionStorage.setItem("splash-seen-ecclesia-connect", "1");
  };

  const desktop = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1.5, colorScheme: "light" });
  await desktop.addInitScript(skipSplash);
  const admin = await shoot(desktop, ADMIN, ADMIN_STOPS, "admin", "/accounts/login/", "admin");

  const phone = await browser.newContext({
    viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: "light",
  });
  await phone.addInitScript(skipSplash);
  const connect = await shoot(phone, MEMBERS, CONNECT_STOPS, "connect", "/login/", MEMBER);

  // The splash screens and sign-in pages, for the page header and the apps section.
  const fresh = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1.5 });
  const splash = await fresh.newPage();
  await splash.goto(ADMIN + "/accounts/login/", { waitUntil: "domcontentloaded" });
  await splash.waitForTimeout(900);
  await splash.screenshot({ path: path.join(OUT, "admin-splash.jpg"), type: "jpeg", quality: 80 });
  const phoneFresh = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true });
  const splashPhone = await phoneFresh.newPage();
  await splashPhone.goto(MEMBERS + "/login/", { waitUntil: "domcontentloaded" });
  await splashPhone.waitForTimeout(900);
  await splashPhone.screenshot({ path: path.join(OUT, "connect-splash.jpg"), type: "jpeg", quality: 80 });

  await browser.close();
  const body = "// Generated by tools/capture-demo.cjs: screenshots and highlight positions (% of the screen).\n"
    + `window.ECCLESIA_SHOTS = ${JSON.stringify({ admin, connect }, null, 1)};\n`;
  fs.writeFileSync(path.join(SITE, "js", "tour-shots.js"), body);
  console.log("Wrote js/tour-shots.js");
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
