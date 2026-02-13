/**
 * JobHunter Dashboard - Interactive tracking, AJAX save, filtering & sorting.
 */

(function () {
  "use strict";

  // ── AJAX save ────────────────────────────────────────────────────────

  let saveTimers = {};

  function saveTracking(offerId, data) {
    fetch("/api/tracking/" + offerId, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (res) {
        if (!res.ok) {
          console.error("Save failed", res.error);
          return;
        }
        var row = document.querySelector('tr[data-offer-id="' + offerId + '"]');
        if (!row) return;

        // Update date labels
        if (res.tracking.date_sent !== undefined) {
          var cvLabel = row.querySelector('[data-field="cv_sent"]')
            .closest("td")
            .querySelector(".date-label");
          cvLabel.textContent = res.tracking.date_sent
            ? formatShort(res.tracking.date_sent)
            : "";
        }
        if (res.tracking.follow_up_date !== undefined) {
          var fuLabel = row.querySelector('[data-field="follow_up_done"]')
            .closest("td")
            .querySelector(".date-label");
          fuLabel.textContent = res.tracking.follow_up_date
            ? formatShort(res.tracking.follow_up_date)
            : "";
        }

        // Update data attribute for filtering
        if (data.status) {
          row.dataset.status = data.status;
        }

        // Update status select color class
        if (data.status) {
          var sel = row.querySelector('[data-field="status"]');
          sel.className =
            "status-select status-color-" +
            data.status.toLowerCase().replace(/ /g, "-");
        }
      })
      .catch(function (err) {
        console.error("Network error:", err);
      });
  }

  function formatShort(dateStr) {
    var parts = dateStr.split("-");
    return parts[1] + "/" + parts[2];
  }

  // ── Event: status dropdown ───────────────────────────────────────────

  document.querySelectorAll(".status-select").forEach(function (sel) {
    sel.addEventListener("change", function () {
      var offerId = this.closest("tr").dataset.offerId;
      saveTracking(offerId, { status: this.value });
    });
  });

  // ── Event: checkboxes ────────────────────────────────────────────────

  document.querySelectorAll(".tracking-checkbox").forEach(function (cb) {
    cb.addEventListener("change", function () {
      var offerId = this.closest("tr").dataset.offerId;
      var field = this.dataset.field;
      var payload = {};
      payload[field] = this.checked;
      saveTracking(offerId, payload);
    });
  });

  // ── Event: notes (debounced) ─────────────────────────────────────────

  document.querySelectorAll(".notes-input").forEach(function (input) {
    input.addEventListener("input", function () {
      var offerId = this.closest("tr").dataset.offerId;
      clearTimeout(saveTimers[offerId]);
      var value = this.value;
      saveTimers[offerId] = setTimeout(function () {
        saveTracking(offerId, { notes: value });
      }, 600);
    });
  });

  // ── Filtering ────────────────────────────────────────────────────────

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

    var rows = document.querySelectorAll(".offer-row");
    var shown = 0;

    rows.forEach(function (row) {
      var show = true;

      if (status && row.dataset.status !== status) show = false;
      if (source && row.dataset.source !== source) show = false;
      if (company && row.dataset.company !== company) show = false;
      if (search) {
        var text = row.dataset.title + " " + row.dataset.company + " " + row.dataset.location;
        if (text.indexOf(search) === -1) show = false;
      }

      row.style.display = show ? "" : "none";
      if (show) shown++;
    });

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

  // ── Column sorting ──────────────────────────────────────────────────

  var currentSort = { col: null, asc: true };

  document.querySelectorAll(".sortable").forEach(function (th) {
    th.addEventListener("click", function () {
      var col = this.dataset.col;
      if (currentSort.col === col) {
        currentSort.asc = !currentSort.asc;
      } else {
        currentSort.col = col;
        currentSort.asc = true;
      }

      // Update sort icons
      document.querySelectorAll(".sortable").forEach(function (h) {
        h.classList.remove("sort-asc", "sort-desc");
      });
      this.classList.add(currentSort.asc ? "sort-asc" : "sort-desc");

      sortTable(col, currentSort.asc);
    });
  });

  function sortTable(col, asc) {
    var tbody = document.querySelector("#offers-table tbody");
    if (!tbody) return;

    var rows = Array.from(tbody.querySelectorAll(".offer-row"));

    rows.sort(function (a, b) {
      var va, vb;

      if (col === "score") {
        va = parseFloat(a.dataset.score) || 0;
        vb = parseFloat(b.dataset.score) || 0;
        return asc ? va - vb : vb - va;
      }

      if (col === "date") {
        va = a.dataset.date || "";
        vb = b.dataset.date || "";
      } else if (col === "title") {
        va = a.dataset.title;
        vb = b.dataset.title;
      } else if (col === "company") {
        va = a.dataset.company;
        vb = b.dataset.company;
      } else if (col === "location") {
        va = a.dataset.location;
        vb = b.dataset.location;
      } else if (col === "source") {
        va = a.dataset.source;
        vb = b.dataset.source;
      } else {
        va = "";
        vb = "";
      }

      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });

    rows.forEach(function (row) {
      tbody.appendChild(row);
    });
  }

  // Keep data-status in sync when status dropdown changes
  document.querySelectorAll(".status-select").forEach(function (sel) {
    sel.addEventListener("change", function () {
      this.closest("tr").dataset.status = this.value;
    });
  });
})();
