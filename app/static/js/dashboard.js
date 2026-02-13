/**
 * JobHunter Dashboard - Interactive tracking, AJAX save, filtering & sorting.
 * Uses event delegation for performance (3 listeners instead of 1200+).
 */

(function () {
  "use strict";

  var tbody = document.querySelector("#offers-table tbody");
  if (!tbody) return;

  // ── Stats counters (optimistic: update before AJAX) ────────────────

  var statCvSent = document.getElementById("stat-cv-sent");
  var statFollowUps = document.getElementById("stat-follow-ups");
  var statInterviews = document.getElementById("stat-interviews");

  // Initialize counters from current DOM state
  var counts = { cv: 0, fu: 0, interviews: 0 };

  (function initCounts() {
    var cbs = tbody.querySelectorAll('[data-field="cv_sent"]');
    for (var i = 0; i < cbs.length; i++) {
      if (cbs[i].checked) counts.cv++;
    }
    var fus = tbody.querySelectorAll('[data-field="follow_up_done"]');
    for (var j = 0; j < fus.length; j++) {
      if (fus[j].checked) counts.fu++;
    }
    var sels = tbody.querySelectorAll('[data-field="status"]');
    for (var k = 0; k < sels.length; k++) {
      if (sels[k].value === "Interview") counts.interviews++;
    }
  })();

  function renderStats() {
    if (statCvSent) statCvSent.textContent = counts.cv;
    if (statFollowUps) statFollowUps.textContent = counts.fu;
    if (statInterviews) statInterviews.textContent = counts.interviews;
  }

  // ── AJAX save (fire-and-forget, UI already updated) ────────────────

  var noteTimers = {};

  function saveTracking(offerId, data) {
    console.time("ajax-save-" + offerId);
    fetch("/api/tracking/" + offerId, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        console.timeEnd("ajax-save-" + offerId);
        if (!res.ok) {
          console.error("Save failed", res.error);
          return;
        }
        console.time("dom-update-" + offerId);
        var row = tbody.querySelector('tr[data-offer-id="' + offerId + '"]');
        if (!row) return;

        if (res.tracking.date_sent !== undefined) {
          var cvLabel = row.querySelector('[data-field="cv_sent"]')
            .closest("td").querySelector(".date-label");
          cvLabel.textContent = res.tracking.date_sent
            ? formatShort(res.tracking.date_sent) : "";
        }
        if (res.tracking.follow_up_date !== undefined) {
          var fuLabel = row.querySelector('[data-field="follow_up_done"]')
            .closest("td").querySelector(".date-label");
          fuLabel.textContent = res.tracking.follow_up_date
            ? formatShort(res.tracking.follow_up_date) : "";
        }
        console.timeEnd("dom-update-" + offerId);
      })
      .catch(function (err) {
        console.timeEnd("ajax-save-" + offerId);
        console.error("Network error:", err);
      });
  }

  function formatShort(dateStr) {
    var parts = dateStr.split("-");
    return parts[1] + "/" + parts[2];
  }

  // ── Event delegation: one "change" listener on tbody ───────────────

  tbody.addEventListener("change", function (e) {
    console.time("change-handler");
    var target = e.target;
    var row = target.closest(".offer-row");
    if (!row) { console.timeEnd("change-handler"); return; }
    var offerId = row.dataset.offerId;

    // Status dropdown
    if (target.dataset.field === "status") {
      var oldStatus = row.dataset.status;
      var newStatus = target.value;

      // Update interview counter
      if (oldStatus === "Interview" && newStatus !== "Interview") counts.interviews--;
      if (oldStatus !== "Interview" && newStatus === "Interview") counts.interviews++;
      renderStats();

      // Update data attribute + color
      row.dataset.status = newStatus;
      target.className = "status-select status-color-" +
        newStatus.toLowerCase().replace(/ /g, "-");

      console.timeEnd("change-handler");
      saveTracking(offerId, { status: newStatus });
      return;
    }

    // Checkboxes (cv_sent, follow_up_done)
    if (target.classList.contains("tracking-checkbox")) {
      var field = target.dataset.field;
      var checked = target.checked;

      // Update counter
      if (field === "cv_sent") counts.cv += checked ? 1 : -1;
      if (field === "follow_up_done") counts.fu += checked ? 1 : -1;
      renderStats();

      var payload = {};
      payload[field] = checked;
      console.timeEnd("change-handler");
      saveTracking(offerId, payload);
      return;
    }
    console.timeEnd("change-handler");
  });

  // ── Event delegation: one "input" listener for notes (debounced) ───

  tbody.addEventListener("input", function (e) {
    var target = e.target;
    if (!target.classList.contains("notes-input")) return;
    var row = target.closest(".offer-row");
    if (!row) return;
    var offerId = row.dataset.offerId;

    clearTimeout(noteTimers[offerId]);
    var value = target.value;
    noteTimers[offerId] = setTimeout(function () {
      saveTracking(offerId, { notes: value });
    }, 600);
  });

  // ── Filtering ──────────────────────────────────────────────────────

  var filterStatus = document.getElementById("filter-status");
  var filterSource = document.getElementById("filter-source");
  var filterCompany = document.getElementById("filter-company");
  var filterSearch = document.getElementById("filter-search");
  var visibleCount = document.getElementById("visible-count");

  function applyFilters() {
    var status = filterStatus ? filterStatus.value : "";
    var source = filterSource ? filterSource.value : "";
    var company = filterCompany ? filterCompany.value.toLowerCase() : "";
    var search = filterSearch ? filterSearch.value.toLowerCase().trim() : "";

    var rows = tbody.querySelectorAll(".offer-row");
    var shown = 0;

    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var show = true;

      if (status && row.dataset.status !== status) show = false;
      if (show && source && row.dataset.source !== source) show = false;
      if (show && company && row.dataset.company !== company) show = false;
      if (show && search) {
        var text = row.dataset.title + " " + row.dataset.company + " " + row.dataset.location;
        if (text.indexOf(search) === -1) show = false;
      }

      row.style.display = show ? "" : "none";
      if (show) shown++;
    }

    if (visibleCount) visibleCount.textContent = shown;
  }

  if (filterStatus) filterStatus.addEventListener("change", applyFilters);
  if (filterSource) filterSource.addEventListener("change", applyFilters);
  if (filterCompany) filterCompany.addEventListener("change", applyFilters);
  if (filterSearch) filterSearch.addEventListener("input", applyFilters);

  var resetBtn = document.getElementById("filters-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", function () {
      if (filterStatus) filterStatus.value = "";
      if (filterSource) filterSource.value = "";
      if (filterCompany) filterCompany.value = "";
      if (filterSearch) filterSearch.value = "";
      applyFilters();
    });
  }

  // ── Column sorting ─────────────────────────────────────────────────

  var currentSort = { col: null, asc: true };
  var sortHeaders = document.querySelectorAll(".sortable");

  sortHeaders.forEach(function (th) {
    th.addEventListener("click", function () {
      var col = this.dataset.col;
      if (currentSort.col === col) {
        currentSort.asc = !currentSort.asc;
      } else {
        currentSort.col = col;
        currentSort.asc = true;
      }

      sortHeaders.forEach(function (h) {
        h.classList.remove("sort-asc", "sort-desc");
      });
      this.classList.add(currentSort.asc ? "sort-asc" : "sort-desc");

      sortTable(col, currentSort.asc);
    });
  });

  function sortTable(col, asc) {
    var rows = Array.from(tbody.querySelectorAll(".offer-row"));

    rows.sort(function (a, b) {
      var va, vb;

      if (col === "score") {
        va = parseFloat(a.dataset.score) || 0;
        vb = parseFloat(b.dataset.score) || 0;
        return asc ? va - vb : vb - va;
      }

      va = a.dataset[col] || "";
      vb = b.dataset[col] || "";

      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });

    for (var i = 0; i < rows.length; i++) {
      tbody.appendChild(rows[i]);
    }
  }
})();
