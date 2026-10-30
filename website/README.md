# Ecclesia website

The marketing website for Ecclesia: features, an interactive demo of both apps, app downloads, pricing and a "Get started" form. It is a plain static site (HTML, CSS and a little JavaScript, no build step), so it can be hosted anywhere: GitHub Pages, Netlify, Cloudflare Pages, or any web server.

## Preview it

```bash
cd website && python3 -m http.server 8080
```

Then open http://localhost:8080.

## Set it up: `js/config.js`

Everything you are likely to change lives in `js/config.js`:

| Setting | What it does |
|---|---|
| `prices` | Monthly price of each plan: Seed KSh 10,000, Harvest KSh 20,000, Kingdom KSh 30,000 |
| `yearlyMonths` | What a year costs, in months. `10` means yearly billing is 10 × the monthly price (two months free); `12` means no discount |
| `contact` | Your email, WhatsApp number and phone. The form sends enquiries by WhatsApp and/or email; until one is set it shows "Online enquiries open soon" |
| `liveDemo` | Addresses of a public demo server (see below). When set, a "Try it yourself" box appears under the tour |
| `downloads` | Google Play, App Store and desktop installer links. Empty links show "Coming soon" |

Plan names, what each plan includes, the FAQ and all other wording are in `index.html`.

## The interactive demo

The tour shows real screens from the sample church, with the relevant part highlighted at each stop.

- The words for each stop are in `js/tour-steps.js`.
- The screenshots (`img/demo/`) and highlight positions (`js/tour-shots.js`) are made by `tools/capture-demo.cjs`. To refresh them after changing the apps, run both apps with the sample church loaded (see the main README), then:

  ```bash
  cd website/tools
  ```

  ```bash
  npm install && npx playwright install chromium
  ```

  ```bash
  npm run capture
  ```

## A live demo church

For a "try it yourself" demo, run a separate Ecclesia server (never your church's real one) with `ECCLESIA_DEMO_MODE=1`. It loads the sample Nairobi church on first start, shows one-click demo logins on both sign-in pages, and blocks password and login changes so one visitor can't lock out the next. Reset it every night with:

```bash
docker compose exec -T admin python manage.py reset_demo
```

`reset_demo` refuses to run unless demo mode is on. Then put the two addresses in `liveDemo` in `js/config.js`.

## Publishing

The site is live at https://pizzatechies.github.io/churchapp/website/. Whenever this folder changes on the main branch, the **Website** GitHub Actions workflow copies it to the `gh-pages` branch.

To serve it at the shorter https://pizzatechies.github.io/churchapp/, set *Settings → Pages → Build and deployment* to *Deploy from a branch*, branch `gh-pages`, folder `/ (root)`. To use your own domain, add it on the same page.
