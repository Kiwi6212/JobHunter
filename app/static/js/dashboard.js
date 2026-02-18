/**
 * JobHunter Dashboard - Interactive tracking, AJAX save, filtering & sorting.
 * Uses event delegation for performance (3 listeners instead of 1200+).
 */

(function () {
  "use strict";

  // ── Translations ────────────────────────────────────────────────────

  // Status value → display label map (values stay in English for DB)
  var STATUS_LABELS = {
    fr: {
      "New":         "Nouveau",
      "Applied":     "Candidature envoyée",
      "Followed up": "Relancé",
      "Interview":   "Entretien",
      "Accepted":    "Accepté",
      "Rejected":    "Refusé",
      "No response": "Sans réponse",
    },
    en: {
      "New":         "New",
      "Applied":     "Applied",
      "Followed up": "Followed up",
      "Interview":   "Interview",
      "Accepted":    "Accepted",
      "Rejected":    "Rejected",
      "No response": "No response",
    }
  };

  var TRANSLATIONS = {
    fr: {
      nav_dashboard:      "Dashboard",
      nav_stats:          "Statistiques",
      dashboard_title:    "Tableau de bord des offres",
      stat_total:         "Total offres",
      stat_cv:            "CV envoyés",
      stat_followup:      "Relances",
      stat_interviews:    "Entretiens",
      filter_status:      "Statut",
      filter_source:      "Source",
      filter_company:     "Entreprise",
      filter_search:      "Recherche",
      filter_all:         "Tous",
      filter_company_ph:  "Filtrer par entreprise...",
      filter_search_ph:   "Rechercher titre, entreprise...",
      filter_all_offers:  "Afficher toutes les offres",
      filter_recruiters:  "Afficher les recruteurs potentiels",
      btn_reset:          "Réinitialiser",
      col_title:          "Titre",
      col_company:        "Entreprise",
      col_location:       "Lieu",
      col_source:         "Source",
      col_date:           "Publié",
      col_score:          "Score",
      col_status:         "Statut",
      col_cv:             "CV envoyé",
      col_followup:       "Relance",
      col_notes:          "Notes",
      col_link:           "Lien",
      btn_view:           "Voir",
      offers_count:       "offres",
      page_label:         "Page",
      empty_title:        "Aucune offre trouvée",
      empty_text:         "Lancez les scrapers pour remplir le tableau de bord.",
      btn_export_csv:     "Exporter CSV",
      stat_targets:       "Offres cibles",
    },
    en: {
      nav_dashboard:      "Dashboard",
      nav_stats:          "Statistics",
      dashboard_title:    "Job Offers Dashboard",
      stat_total:         "Total Offers",
      stat_cv:            "CV Sent",
      stat_followup:      "Follow-ups",
      stat_interviews:    "Interviews",
      filter_status:      "Status",
      filter_source:      "Source",
      filter_company:     "Company",
      filter_search:      "Search",
      filter_all:         "All",
      filter_company_ph:  "Filter by company...",
      filter_search_ph:   "Search title, company...",
      filter_all_offers:  "Show all offers",
      filter_recruiters:  "Show potential recruiters",
      btn_reset:          "Reset",
      col_title:          "Title",
      col_company:        "Company",
      col_location:       "Location",
      col_source:         "Source",
      col_date:           "Posted",
      col_score:          "Score",
      col_status:         "Status",
      col_cv:             "CV Sent",
      col_followup:       "Follow-up",
      col_notes:          "Notes",
      col_link:           "Link",
      btn_view:           "View",
      offers_count:       "offers",
      page_label:         "Page",
      empty_title:        "No job offers found",
      empty_text:         "Run the scrapers to populate the dashboard with job offers.",
      btn_export_csv:     "Export CSV",
      stat_targets:       "Target offers",
    }
  };

  var currentLang = localStorage.getItem("jh-lang") || "fr";

  function applyLang(lang) {
    var t = TRANSLATIONS[lang] || TRANSLATIONS.fr;
    currentLang = lang;

    // Update text content for all data-i18n elements
    var els = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < els.length; i++) {
      var key = els[i].getAttribute("data-i18n");
      if (t[key] !== undefined) els[i].textContent = t[key];
    }

    // Update placeholder attributes
    var pls = document.querySelectorAll("[data-i18n-placeholder]");
    for (var j = 0; j < pls.length; j++) {
      var pkey = pls[j].getAttribute("data-i18n-placeholder");
      if (t[pkey] !== undefined) pls[j].placeholder = t[pkey];
    }

    // Translate status select options (value stays English, label changes)
    translateStatusSelects(lang);

    // Re-render pagination label in current language
    renderPage();
  }

  function translateStatusSelects(lang) {
    var labels = STATUS_LABELS[lang] || STATUS_LABELS.en;
    // Covers the filter dropdown (#filter-status) and all per-row status selects
    var selects = document.querySelectorAll('[data-field="status"], #filter-status');
    for (var i = 0; i < selects.length; i++) {
      var opts = selects[i].options;
      for (var j = 0; j < opts.length; j++) {
        var val = opts[j].value;
        if (val && labels[val] !== undefined) {
          opts[j].textContent = labels[val];
        }
      }
    }
  }

  // Listen for language change events dispatched by base.html
  document.addEventListener("jh-lang-change", function (e) {
    applyLang(e.detail.lang);
  });

  // ── Guard: early return if no table (non-dashboard pages) ───────────

  var tbody = document.querySelector("#offers-table tbody");
  if (!tbody) {
    applyLang(currentLang);
    return;
  }

  // ── Stats counters (optimistic: update before AJAX) ────────────────

  var statCvSent    = document.getElementById("stat-cv-sent");
  var statFollowUps = document.getElementById("stat-follow-ups");
  var statInterviews = document.getElementById("stat-interviews");

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
    if (statCvSent)     statCvSent.textContent     = counts.cv;
    if (statFollowUps)  statFollowUps.textContent  = counts.fu;
    if (statInterviews) statInterviews.textContent = counts.interviews;
  }

  // ── AJAX save (fire-and-forget, UI already updated) ────────────────

  var noteTimers = {};

  function saveTracking(offerId, data) {
    var t0 = performance.now();
    console.log("[DIAG] fetch START offer=" + offerId, data);
    fetch("/api/tracking/" + offerId, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
      .then(function (r) {
        var t1 = performance.now();
        console.log("[DIAG] fetch response received offer=" + offerId +
          " status=" + r.status + " (" + (t1 - t0).toFixed(1) + "ms)");
        return r.json();
      })
      .then(function (res) {
        var t2 = performance.now();
        console.log("[DIAG] json parsed offer=" + offerId +
          " (" + (t2 - t0).toFixed(1) + "ms total)");
        if (res.server_ms !== undefined) {
          console.log("[DIAG] server processing: " + res.server_ms + "ms");
        }
        if (!res.ok) {
          console.error("Save failed", res.error);
          return;
        }
        var t3 = performance.now();
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
        var t4 = performance.now();
        console.log("[DIAG] dom-update offer=" + offerId +
          " (" + (t4 - t3).toFixed(1) + "ms)");
      })
      .catch(function (err) {
        console.error("[DIAG] Network error after " +
          (performance.now() - t0).toFixed(1) + "ms:", err);
      });
  }

  function formatShort(dateStr) {
    var parts = dateStr.split("-");
    return parts[1] + "/" + parts[2];
  }

  // ── Event delegation: one "change" listener on tbody ───────────────

  tbody.addEventListener("change", function (e) {
    var t0 = performance.now();
    var target = e.target;
    var row = target.closest(".offer-row");
    if (!row) {
      console.log("[DIAG] change: no .offer-row (" + (performance.now() - t0).toFixed(1) + "ms)");
      return;
    }
    var offerId = row.dataset.offerId;
    var t1 = performance.now();
    console.log("[DIAG] change: row lookup (" + (t1 - t0).toFixed(1) + "ms)");

    // Status dropdown
    if (target.dataset.field === "status") {
      var oldStatus = row.dataset.status;
      var newStatus = target.value;

      if (oldStatus === "Interview" && newStatus !== "Interview") counts.interviews--;
      if (oldStatus !== "Interview" && newStatus === "Interview") counts.interviews++;
      var t2 = performance.now();
      console.log("[DIAG] change: counter update (" + (t2 - t1).toFixed(1) + "ms)");

      renderStats();
      var t3 = performance.now();
      console.log("[DIAG] change: renderStats (" + (t3 - t2).toFixed(1) + "ms)");

      row.dataset.status = newStatus;
      target.className = "status-select status-color-" +
        newStatus.toLowerCase().replace(/ /g, "-");
      var t4 = performance.now();
      console.log("[DIAG] change: DOM class update (" + (t4 - t3).toFixed(1) + "ms)");
      console.log("[DIAG] change TOTAL (status) = " + (t4 - t0).toFixed(1) + "ms → calling fetch");

      saveTracking(offerId, { status: newStatus });
      return;
    }

    // Checkboxes (cv_sent, follow_up_done)
    if (target.classList.contains("tracking-checkbox")) {
      var field   = target.dataset.field;
      var checked = target.checked;

      if (field === "cv_sent")       counts.cv += checked ? 1 : -1;
      if (field === "follow_up_done") counts.fu += checked ? 1 : -1;
      var t2b = performance.now();
      console.log("[DIAG] change: counter update (" + (t2b - t1).toFixed(1) + "ms)");

      renderStats();
      var t3b = performance.now();
      console.log("[DIAG] change: renderStats (" + (t3b - t2b).toFixed(1) + "ms)");

      var payload = {};
      payload[field] = checked;
      console.log("[DIAG] change TOTAL (checkbox) = " + (t3b - t0).toFixed(1) + "ms → calling fetch");

      saveTracking(offerId, payload);
      return;
    }
    console.log("[DIAG] change: unhandled target (" + (performance.now() - t0).toFixed(1) + "ms)");
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

  // ── Filtering + Pagination ─────────────────────────────────────────

  var PAGE_SIZE    = 25;
  var currentPage  = 0;
  var filteredRows = [];
  var allRows      = Array.from(tbody.querySelectorAll(".offer-row"));

  var filterStatus  = document.getElementById("filter-status");
  var filterSource  = document.getElementById("filter-source");
  var filterCompany = document.getElementById("filter-company");
  var filterSearch  = document.getElementById("filter-search");
  var showRecruiters = document.getElementById("show-recruiters");
  var showAllOffers  = document.getElementById("show-all-offers");
  var visibleCount   = document.getElementById("visible-count");
  var pageInfo       = document.getElementById("page-info");
  var pageNext       = document.getElementById("page-next");
  var pagePrev       = document.getElementById("page-prev");

  function applyFilters() {
    var status  = filterStatus  ? filterStatus.value  : "";
    var source  = filterSource  ? filterSource.value  : "";
    var company = filterCompany ? filterCompany.value.toLowerCase().trim() : "";
    var search  = filterSearch  ? filterSearch.value.toLowerCase().trim()  : "";
    var includeRecruiters = showRecruiters ? showRecruiters.checked : false;
    var showAll           = showAllOffers  ? showAllOffers.checked  : false;

    filteredRows = [];
    for (var i = 0; i < allRows.length; i++) {
      var row  = allRows[i];
      var show = true;

      // Hide recruiters unless toggle is checked
      if (!includeRecruiters && row.dataset.offerType === "recruiter") show = false;
      // By default show only target companies; show all when toggle is checked
      if (show && !showAll && row.dataset.target !== "1") show = false;
      if (show && status  && row.dataset.status !== status)                          show = false;
      if (show && source  && row.dataset.source !== source)                          show = false;
      if (show && company && row.dataset.company.indexOf(company) === -1)            show = false;
      if (show && search) {
        var text = row.dataset.title + " " + row.dataset.company + " " + row.dataset.location;
        if (text.indexOf(search) === -1) show = false;
      }

      if (show) filteredRows.push(row);
    }

    currentPage = 0;
    renderPage();
  }

  function renderPage() {
    var t = TRANSLATIONS[currentLang] || TRANSLATIONS.fr;
    var totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
    if (currentPage >= totalPages) currentPage = totalPages - 1;
    var start = currentPage * PAGE_SIZE;
    var end   = start + PAGE_SIZE;

    for (var i = 0; i < allRows.length; i++) {
      allRows[i].style.display = "none";
    }
    for (var j = start; j < end && j < filteredRows.length; j++) {
      filteredRows[j].style.display = "";
    }

    if (visibleCount) visibleCount.textContent = filteredRows.length;
    if (pageInfo) pageInfo.textContent = t.page_label + " " + (currentPage + 1) + " / " + totalPages;
    if (pagePrev) pagePrev.disabled = currentPage === 0;
    if (pageNext) pageNext.disabled = currentPage >= totalPages - 1;
  }

  if (filterStatus)  filterStatus.addEventListener("change", applyFilters);
  if (filterSource)  filterSource.addEventListener("change", applyFilters);
  if (filterCompany) filterCompany.addEventListener("input",  applyFilters);
  if (filterSearch)  filterSearch.addEventListener("input",   applyFilters);
  if (showRecruiters) showRecruiters.addEventListener("change", applyFilters);
  if (showAllOffers)  showAllOffers.addEventListener("change",  applyFilters);

  if (pageNext) pageNext.addEventListener("click", function () { currentPage++; renderPage(); });
  if (pagePrev) pagePrev.addEventListener("click", function () { currentPage--; renderPage(); });

  var resetBtn = document.getElementById("filters-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", function () {
      if (filterStatus)  filterStatus.value  = "";
      if (filterSource)  filterSource.value  = "";
      if (filterCompany) filterCompany.value = "";
      if (filterSearch)  filterSearch.value  = "";
      if (showRecruiters) showRecruiters.checked = false;
      if (showAllOffers)  showAllOffers.checked  = false;
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
    function cmp(a, b) {
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
    }

    allRows.sort(cmp);
    for (var i = 0; i < allRows.length; i++) {
      tbody.appendChild(allRows[i]);
    }

    applyFilters();
  }

  // ── CSV Export ─────────────────────────────────────────────────────

  var exportBtn = document.getElementById("export-csv");
  if (exportBtn) {
    exportBtn.addEventListener("click", exportCSV);
  }

  function exportCSV() {
    var t = TRANSLATIONS[currentLang] || TRANSLATIONS.fr;
    var labels = STATUS_LABELS[currentLang] || STATUS_LABELS.en;

    // CSV headers in current UI language
    var headers = [
      t.col_title, t.col_company, t.col_location, t.col_source,
      t.col_date, t.col_score, t.col_status, t.col_cv, t.col_followup,
      t.col_notes, "URL"
    ];

    var rows = [headers];

    // Export ALL filtered rows (not just current page)
    for (var i = 0; i < filteredRows.length; i++) {
      var row = filteredRows[i];
      var statusVal = row.dataset.status;

      rows.push([
        row.querySelector(".offer-title").textContent.trim(),
        row.querySelector(".col-company").textContent.trim(),
        row.querySelector(".col-location").textContent.trim(),
        row.dataset.source,
        row.dataset.date,
        row.dataset.score,
        labels[statusVal] || statusVal,
        row.querySelector('[data-field="cv_sent"]').checked ? "1" : "0",
        row.querySelector('[data-field="follow_up_done"]').checked ? "1" : "0",
        row.querySelector(".notes-input").value,
        row.querySelector(".btn-view").href,
      ]);
    }

    // Build CSV with proper quoting
    var csv = rows.map(function (r) {
      return r.map(function (cell) {
        var s = String(cell === null || cell === undefined ? "" : cell);
        if (s.indexOf(",") !== -1 || s.indexOf('"') !== -1 || s.indexOf("\n") !== -1) {
          s = '"' + s.replace(/"/g, '""') + '"';
        }
        return s;
      }).join(",");
    }).join("\n");

    // BOM + download trigger (BOM ensures correct UTF-8 in Excel)
    var blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    var blobUrl = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = blobUrl;
    a.download = "jobhunter-" + new Date().toISOString().slice(0, 10) + ".csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);
  }

  // ── Initial render ─────────────────────────────────────────────────
  applyFilters();
  applyLang(currentLang);

})();
