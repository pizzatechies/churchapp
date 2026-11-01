/* Members app giving charts. Colors come from the validated chart tokens in app.css, so light and dark modes each use their own steps. */
(function () {
  "use strict";
  if (typeof Chart === "undefined") return;

  var charts = [];

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function data(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
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

  function options(showSeriesName) {
    var grid = css("--chart-grid"), text = css("--chart-text");
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (ctx) { return " " + (showSeriesName ? ctx.dataset.label + ": " : "") + money(ctx.parsed.y); },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { color: grid }, ticks: { color: text, maxRotation: 0, autoSkip: true } },
        y: { beginAtZero: true, grid: { color: grid, lineWidth: 1 }, border: { display: false },
             ticks: { color: text, callback: compact, maxTicksLimit: 5 } },
      },
    };
  }

  function bar(label, values, color) {
    return {
      label: label, data: values, backgroundColor: color,
      borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "start",
      maxBarThickness: 28, categoryPercentage: 0.72, barPercentage: 0.9,
    };
  }

  function draw() {
    charts.forEach(function (c) { c.destroy(); });
    charts = [];
    var s1 = css("--series-1"), s2 = css("--series-2");

    var church = data("data-church"), el = document.getElementById("chartChurch");
    if (church && el) {
      charts.push(new Chart(el, {
        type: "bar",
        data: { labels: church.labels, datasets: [bar("Income", church.income, s1), bar("Spending", church.expense, s2)] },
        options: options(true),
      }));
    }

    var mine = data("data-mine"), el2 = document.getElementById("chartMine");
    if (mine && el2) {
      charts.push(new Chart(el2, {
        type: "bar",
        data: { labels: mine.labels, datasets: [bar("Given", mine.amounts, s1)] },
        options: options(false),
      }));
    }
  }

  draw();
  document.addEventListener("themechange", draw);
})();
