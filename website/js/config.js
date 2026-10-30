// Website settings. Edit this file; the rest of the site reads from it.
window.ECCLESIA_SITE = {
  currency: "KSh",

  // Monthly price of each plan. The plan names and what each includes are in index.html.
  prices: { seed: 10000, harvest: 20000, kingdom: 30000 },
  // Paying yearly costs this many months (10 = two months free).
  yearlyMonths: 10,

  // How people reach you from the "Get started" form. Leave a value empty to hide it.
  contact: {
    email: "pizzatechies@gmail.com",
    whatsapp: "254747354677",   // international format without "+"
    phone: "+254 747 354 677",
  },

  // A public demo server (ECCLESIA_DEMO_MODE=1, see the main README). Empty hides the buttons.
  liveDemo: {
    admin: "",      // e.g. "https://demo-admin.example.com"
    members: "",    // e.g. "https://demo-members.example.com"
  },

  // Download links. Empty shows "Coming soon".
  downloads: {
    android: "",    // Google Play listing
    ios: "",        // App Store listing
    windows: "",    // e.g. the GitHub release .exe
    mac: "",
    linux: "",
  },
};
