/* Small progressive enhancements. Every page also works without JavaScript. */
(function () {
  "use strict";

  function parseAmount(value) {
    var n = parseFloat(String(value || "").replace(/,/g, ""));
    return isNaN(n) ? 0 : n;
  }

  function fmt(n) {
    var sign = n < 0 ? "-" : "";
    return sign + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  window.appFormat = fmt;
  window.appParse = parseAmount;

  // Sidebar on small screens
  document.querySelectorAll("[data-toggle-sidebar]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.getElementById("sidebar").classList.toggle("show");
    });
  });

  // Dark mode toggle
  document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var root = document.documentElement;
      var next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-bs-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) {}
      document.dispatchEvent(new CustomEvent("themechange"));
    });
  });

  // Confirmation prompts on destructive actions
  document.addEventListener("submit", function (e) {
    var msg = e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // Clickable table rows
  document.querySelectorAll("tr[data-href]").forEach(function (row) {
    row.classList.add("row-link");
    row.addEventListener("click", function (e) {
      if (e.target.closest("a, button, input, select, label, form")) return;
      window.location = row.getAttribute("data-href");
    });
  });

  // Auto-submit filter selects
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form.submit(); });
  });

  // Choosing a preset period clears any custom dates
  document.querySelectorAll("select[data-period-select]").forEach(function (sel) {
    sel.addEventListener("change", function () {
      sel.form.querySelectorAll("input[name=start], input[name=end]").forEach(function (i) { i.value = ""; });
      sel.form.submit();
    });
  });

  // ---- Formsets: add / remove rows ------------------------------------
  document.querySelectorAll("[data-formset]").forEach(function (container) {
    var prefix = container.getAttribute("data-formset");
    var totalInput = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
    var template = container.querySelector("template");
    var body = container.querySelector("[data-formset-body]");
    var addBtn = container.querySelector("[data-formset-add]");

    function bindRow(row) {
      var del = row.querySelector("[data-formset-remove]");
      if (del) {
        del.addEventListener("click", function () {
          var checkbox = row.querySelector("input[name$='-DELETE']");
          if (checkbox) {
            checkbox.checked = true;
            row.classList.add("is-deleted");
          } else {
            row.remove();
          }
          container.dispatchEvent(new Event("input", { bubbles: true }));
        });
      }
    }

    body.querySelectorAll("[data-formset-row]").forEach(bindRow);

    if (addBtn && template && totalInput) {
      addBtn.addEventListener("click", function () {
        var index = parseInt(totalInput.value, 10);
        var html = template.innerHTML.replace(/__prefix__/g, String(index));
        var tmp = document.createElement("tbody");
        tmp.innerHTML = html.trim();
        var row = tmp.firstElementChild;
        // Copy fund / account selections from the previous visible row for faster entry
        var rows = body.querySelectorAll("[data-formset-row]:not(.is-deleted)");
        var last = rows[rows.length - 1];
        if (last) {
          row.querySelectorAll("select[data-sticky]").forEach(function (sel) {
            var name = sel.name.replace(/-\d+-/, "-");
            last.querySelectorAll("select").forEach(function (prev) {
              if (prev.name.replace(/-\d+-/, "-") === name) sel.value = prev.value;
            });
          });
        }
        body.appendChild(row);
        totalInput.value = index + 1;
        bindRow(row);
        var first = row.querySelector("select, input:not([type=hidden])");
        if (first) first.focus();
      });
    }
  });

  // ---- Live totals for line-item tables ---------------------------------
  document.querySelectorAll("[data-line-totals]").forEach(function (table) {
    function recalc() {
      var debit = 0, credit = 0, amount = 0;
      table.querySelectorAll("[data-formset-row]:not(.is-deleted)").forEach(function (row) {
        row.querySelectorAll("input[data-col='debit']").forEach(function (i) { debit += parseAmount(i.value); });
        row.querySelectorAll("input[data-col='credit']").forEach(function (i) { credit += parseAmount(i.value); });
        row.querySelectorAll("input[data-col='amount']").forEach(function (i) { amount += parseAmount(i.value); });
      });
      var set = function (sel, v) { table.querySelectorAll(sel).forEach(function (el) { el.textContent = fmt(v); }); };
      set("[data-total='debit']", debit);
      set("[data-total='credit']", credit);
      set("[data-total='amount']", amount);
      var diff = Math.round((debit - credit) * 100) / 100;
      table.querySelectorAll("[data-total='difference']").forEach(function (el) {
        el.textContent = diff === 0 ? "Balanced" : "Out of balance by " + fmt(Math.abs(diff));
        el.className = diff === 0 ? "badge text-bg-success" : "badge text-bg-danger";
      });
    }
    table.addEventListener("input", recalc);
    table.addEventListener("change", recalc);
    recalc();
  });

  // ---- Budget grid -------------------------------------------------------
  document.querySelectorAll("[data-budget-grid]").forEach(function (grid) {
    function rowTotal(row) {
      var t = 0;
      row.querySelectorAll("input[data-month]").forEach(function (i) { t += parseAmount(i.value); });
      var annual = row.querySelector("input[data-annual]");
      if (annual && document.activeElement !== annual) annual.value = t ? t.toFixed(2) : "";
      return t;
    }
    function totals() {
      var sections = {};
      grid.querySelectorAll("tr[data-row]").forEach(function (row) {
        var type = row.getAttribute("data-type");
        sections[type] = sections[type] || { months: new Array(12).fill(0), total: 0 };
        row.querySelectorAll("input[data-month]").forEach(function (i) {
          sections[type].months[parseInt(i.getAttribute("data-month"), 10)] += parseAmount(i.value);
        });
        sections[type].total += rowTotal(row);
      });
      Object.keys(sections).forEach(function (type) {
        var s = sections[type];
        grid.querySelectorAll("[data-sum='" + type + "']").forEach(function (cell) {
          var m = cell.getAttribute("data-m");
          cell.textContent = fmt(m === "total" ? s.total : s.months[parseInt(m, 10)]);
        });
      });
      var inc = sections.income || { months: new Array(12).fill(0), total: 0 };
      var exp = sections.expense || { months: new Array(12).fill(0), total: 0 };
      grid.querySelectorAll("[data-sum='net']").forEach(function (cell) {
        var m = cell.getAttribute("data-m");
        var v = m === "total" ? inc.total - exp.total : inc.months[+m] - exp.months[+m];
        cell.textContent = fmt(v);
        cell.classList.toggle("text-negative", v < 0);
      });
    }
    grid.addEventListener("input", function (e) {
      if (e.target.hasAttribute("data-annual")) {
        var row = e.target.closest("tr");
        var annual = parseAmount(e.target.value);
        var cents = Math.round(annual * 100);
        var base = Math.floor(cents / 12);
        var extra = cents - base * 12;
        row.querySelectorAll("input[data-month]").forEach(function (i, idx) {
          var v = base + (idx < extra ? 1 : 0);
          i.value = cents ? (v / 100).toFixed(2) : "";
        });
      }
      totals();
    });
    totals();
  });

  // ---- Bank reconciliation -----------------------------------------------
  document.querySelectorAll("[data-reconcile]").forEach(function (form) {
    var begin = parseAmount(form.getAttribute("data-beginning"));
    var statement = parseAmount(form.getAttribute("data-statement"));
    function recalc() {
      var cleared = 0, deposits = 0, payments = 0, nDep = 0, nPay = 0;
      form.querySelectorAll("input[data-amount]").forEach(function (cb) {
        if (!cb.checked) return;
        var a = parseAmount(cb.getAttribute("data-amount"));
        cleared += a;
        if (a >= 0) { deposits += a; nDep++; } else { payments += a; nPay++; }
      });
      var clearedBalance = Math.round((begin + cleared) * 100) / 100;
      var diff = Math.round((statement - clearedBalance) * 100) / 100;
      var set = function (key, v) { form.querySelectorAll("[data-out='" + key + "']").forEach(function (el) { el.textContent = v; }); };
      set("deposits", fmt(deposits) + " (" + nDep + ")");
      set("payments", fmt(-payments) + " (" + nPay + ")");
      set("cleared", fmt(clearedBalance));
      set("difference", fmt(diff));
      form.querySelectorAll("[data-out='difference']").forEach(function (el) {
        el.classList.toggle("text-negative", diff !== 0);
        el.classList.toggle("text-positive", diff === 0);
      });
      form.querySelectorAll("[data-finish]").forEach(function (b) { b.disabled = diff !== 0; });
    }
    form.addEventListener("change", recalc);
    form.querySelectorAll("[data-check-all]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var kind = btn.getAttribute("data-check-all");
        form.querySelectorAll("input[data-amount]").forEach(function (cb) {
          var a = parseAmount(cb.getAttribute("data-amount"));
          if (kind === "all" || (kind === "in" && a >= 0) || (kind === "out" && a < 0)) cb.checked = true;
          if (kind === "none") cb.checked = false;
        });
        recalc();
      });
    });
    recalc();
  });

  // ---- Envelope number lookup on contribution entry -----------------------
  document.querySelectorAll("[data-envelope-lookup]").forEach(function (input) {
    var select = document.getElementById(input.getAttribute("data-envelope-lookup"));
    if (!select) return;
    input.addEventListener("change", function () {
      var env = input.value.trim();
      if (!env) return;
      var found = select.querySelector("option[data-envelope='" + env.replace(/'/g, "") + "']");
      if (found) {
        select.value = found.value;
        input.classList.remove("is-invalid");
        select.dispatchEvent(new Event("change"));
      } else {
        input.classList.add("is-invalid");
      }
    });
  });

  // Pre-select a fund's default income category when the fund changes
  document.querySelectorAll("select[data-fund-defaults]").forEach(function (fundSelect) {
    var map = JSON.parse(fundSelect.getAttribute("data-fund-defaults") || "{}");
    var target = document.getElementById(fundSelect.getAttribute("data-category-target"));
    fundSelect.addEventListener("change", function () {
      if (target && map[fundSelect.value]) target.value = map[fundSelect.value];
    });
  });
})();
