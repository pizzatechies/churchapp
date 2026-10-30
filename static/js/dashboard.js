/* Dashboard charts. Colors come from CSS custom properties so light and dark modes each use their validated steps. */
(function () {
  "use strict";
  if (typeof Chart === "undefined") return;

  var charts = [];

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function compact(v) {
    var a = Math.abs(v);
    if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (a >= 1e4) return Math.round(v / 1e3) + "K";
    return v.toLocaleString();
  }

  function money(v) {
    return v == null ? "—" : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function baseOptions() {
    var grid = css("--chart-grid"), text = css("--chart-text");
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: function (ctx) { return " " + ctx.dataset.label + ": " + money(ctx.parsed.y); } },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { color: grid }, ticks: { color: text, maxRotation: 0, autoSkip: true } },
        y: { beginAtZero: true, grid: { color: grid, lineWidth: 1 }, border: { display: false },
             ticks: { color: text, callback: compact, maxTicksLimit: 6 } },
      },
    };
  }

  function draw() {
    charts.forEach(function (c) { c.destroy(); });
    charts = [];
    var s1 = css("--series-1"), s2 = css("--series-2"), muted = css("--series-muted"), surface = css("--app-card-bg") || "#fff";

    var months = JSON.parse(document.getElementById("data-months").textContent);
    var el = document.getElementById("chartMonths");
    if (el) {
      charts.push(new Chart(el, {
        type: "bar",
        data: {
          labels: months.labels,
          datasets: [
            { label: "Income", data: months.income, backgroundColor: s1, borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "start", maxBarThickness: 24, categoryPercentage: 0.7, barPercentage: 0.9 },
            { label: "Expenses", data: months.expense, backgroundColor: s2, borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "start", maxBarThickness: 24, categoryPercentage: 0.7, barPercentage: 0.9 },
          ],
        },
        options: baseOptions(),
      }));
    }

    var giving = JSON.parse(document.getElementById("data-giving").textContent);
    var el2 = document.getElementById("chartGiving");
    if (el2) {
      charts.push(new Chart(el2, {
        type: "line",
        data: {
          labels: giving.labels,
          datasets: [
            { label: giving.previous_label, data: giving.previous, borderColor: muted, backgroundColor: muted, borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.25, spanGaps: false },
            { label: giving.current_label, data: giving.current, borderColor: s1, backgroundColor: s1, borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, pointBorderColor: surface, pointBorderWidth: 2, tension: 0.25, spanGaps: false },
          ],
        },
        options: baseOptions(),
      }));
    }
  }

  draw();
  document.addEventListener("themechange", draw);
})();
