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
      filter_domain:      "Domaine",
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
      btn_import_cv:      "Importer CV",
      btn_rematch_cv:     "Recalculer",
      btn_rematch_claude: "Match IA",
      col_cv_match:       "Match CV",
      cv_uploading:       "Chargement…",
      cv_ai_loading:      "Analyse IA en cours…",
      cv_success:         "CV importé, scores calculés.",
      cv_ai_success:      "Scores IA calculés.",
      cv_match_started:   "Matching lancé…",
      cv_match_done:      "Matching terminé, rechargement…",
      cv_match_running:   "Déjà en cours — suivi de progression repris.",
      cv_error:           "Erreur : ",
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
      filter_domain:      "Domain",
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
      btn_import_cv:      "Import CV",
      btn_rematch_cv:     "Recalculate",
      btn_rematch_claude: "AI Match",
      col_cv_match:       "CV Match",
      cv_uploading:       "Uploading…",
      cv_ai_loading:      "AI analysis in progress…",
      cv_success:         "CV imported, scores calculated.",
      cv_ai_success:      "AI scores calculated.",
      cv_match_started:   "Matching started…",
      cv_match_done:      "Matching complete, reloading…",
      cv_match_running:   "Already running — resuming progress tracking.",
      cv_error:           "Error: ",
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
    // [DIAG] fetch START offer=" + offerId, data);
    fetch("/api/tracking/" + offerId, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
      .then(function (r) {
        var t1 = performance.now();
        // [DIAG] fetch response offer=" + offerId + " status=" + r.status + " (" + (t1 - t0).toFixed(1) + "ms)"
        return r.json();
      })
      .then(function (res) {
        var t2 = performance.now();
        // [DIAG] json parsed offer=" + offerId + " (" + (t2 - t0).toFixed(1) + "ms total)"
        if (res.server_ms !== undefined) {
          // [DIAG] server processing: " + res.server_ms + "ms"
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
        // [DIAG] dom-update offer=" + offerId + " (" + (t4 - t3).toFixed(1) + "ms)"
      })
      .catch(function (err) {
        console.error("Save failed:", err);
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
      // [DIAG] change: no .offer-row (" + (performance.now() - t0).toFixed(1) + "ms)");
      return;
    }
    var offerId = row.dataset.offerId;
    var t1 = performance.now();
    // [DIAG] change: row lookup (" + (t1 - t0).toFixed(1) + "ms)");

    // Status dropdown
    if (target.dataset.field === "status") {
      var oldStatus = row.dataset.status;
      var newStatus = target.value;

      if (oldStatus === "Interview" && newStatus !== "Interview") counts.interviews--;
      if (oldStatus !== "Interview" && newStatus === "Interview") counts.interviews++;
      var t2 = performance.now();
      // [DIAG] change: counter update (" + (t2 - t1).toFixed(1) + "ms)");

      renderStats();
      var t3 = performance.now();
      // [DIAG] change: renderStats (" + (t3 - t2).toFixed(1) + "ms)");

      row.dataset.status = newStatus;
      target.className = "status-select status-color-" +
        newStatus.toLowerCase().replace(/ /g, "-");
      var t4 = performance.now();
      // [DIAG] change: DOM class update (" + (t4 - t3).toFixed(1) + "ms)");
      // [DIAG] change TOTAL (status) = " + (t4 - t0).toFixed(1) + "ms → calling fetch");

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
      // [DIAG] change: counter update (" + (t2b - t1).toFixed(1) + "ms)");

      renderStats();
      var t3b = performance.now();
      // [DIAG] change: renderStats (" + (t3b - t2b).toFixed(1) + "ms)");

      var payload = {};
      payload[field] = checked;
      // [DIAG] change TOTAL (checkbox) = " + (t3b - t0).toFixed(1) + "ms → calling fetch");

      saveTracking(offerId, payload);
      return;
    }
    // [DIAG] change: unhandled target (" + (performance.now() - t0).toFixed(1) + "ms)");
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

  var filterStatus   = document.getElementById("filter-status");
  var filterSource   = document.getElementById("filter-source");
  var filterDomain   = document.getElementById("filter-domain");
  var filterCompany  = document.getElementById("filter-company");
  var filterLocation = document.getElementById("filter-location");
  var filterContract = document.getElementById("filter-contract");
  var filterSearch   = document.getElementById("filter-search");
  var showRecruiters = document.getElementById("show-recruiters");
  var showAllOffers  = document.getElementById("show-all-offers");
  var visibleCount   = document.getElementById("visible-count");
  var pageInfo       = document.getElementById("page-info");
  var pageNext       = document.getElementById("page-next");
  var pagePrev       = document.getElementById("page-prev");

  function applyFilters() {
    var status   = filterStatus   ? filterStatus.value                        : "";
    var source   = filterSource   ? filterSource.value                        : "";
    var domain   = filterDomain   ? filterDomain.value                        : "";
    var company  = filterCompany  ? filterCompany.value.toLowerCase().trim()  : "";
    var location = filterLocation ? filterLocation.value.toLowerCase().trim() : "";
    var contract = filterContract ? filterContract.value                      : "";
    var search   = filterSearch   ? filterSearch.value.toLowerCase().trim()   : "";
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
      if (show && domain  && row.dataset.domainId !== domain)                        show = false;
      if (show && company  && row.dataset.company.indexOf(company) === -1)            show = false;
      if (show && location && row.dataset.location.indexOf(location) === -1)         show = false;
      if (show && contract && row.dataset.contractType !== contract)                 show = false;
      if (show && search) {
        var text = row.dataset.title + " " + row.dataset.company + " " + row.dataset.location;
        if (text.indexOf(search) === -1) show = false;
      }

      if (show) filteredRows.push(row);
    }

    currentPage = 0;
    renderPage();
    saveState();
  }

  function renderPage() {
    var t = TRANSLATIONS[currentLang] || TRANSLATIONS.fr;
    var totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
    if (currentPage >= totalPages) currentPage = totalPages - 1;
    var start = currentPage * PAGE_SIZE;
    var end   = start + PAGE_SIZE;

    for (var i = 0; i < allRows.length; i++) {
      allRows[i].classList.add("hidden");
    }
    for (var j = start; j < end && j < filteredRows.length; j++) {
      filteredRows[j].classList.remove("hidden");
    }

    if (visibleCount) visibleCount.textContent = filteredRows.length;
    if (pageInfo) pageInfo.textContent = t.page_label + " " + (currentPage + 1) + " / " + totalPages;
    if (pagePrev) pagePrev.disabled = currentPage === 0;
    if (pageNext) pageNext.disabled = currentPage >= totalPages - 1;
  }

  if (filterStatus)   filterStatus.addEventListener("change",  applyFilters);
  if (filterSource)   filterSource.addEventListener("change",  applyFilters);
  if (filterDomain)   filterDomain.addEventListener("change",  applyFilters);
  if (filterCompany)  filterCompany.addEventListener("input",   applyFilters);
  if (filterLocation) filterLocation.addEventListener("input",  applyFilters);
  if (filterContract) filterContract.addEventListener("change", applyFilters);
  if (filterSearch)   filterSearch.addEventListener("input",    applyFilters);
  if (showRecruiters) showRecruiters.addEventListener("change", applyFilters);
  if (showAllOffers)  showAllOffers.addEventListener("change",  applyFilters);

  if (pageNext) pageNext.addEventListener("click", function () { currentPage++; renderPage(); saveState(); });
  if (pagePrev) pagePrev.addEventListener("click", function () { currentPage--; renderPage(); saveState(); });

  var resetBtn = document.getElementById("filters-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", function () {
      if (filterStatus)   filterStatus.value   = "";
      if (filterSource)   filterSource.value   = "";
      if (filterDomain)   filterDomain.value   = "";
      if (filterCompany)  filterCompany.value  = "";
      if (filterLocation) filterLocation.value = "";
      if (filterContract) filterContract.value = "";
      if (filterSearch)   filterSearch.value   = "";
      if (showRecruiters) showRecruiters.checked = false;
      if (showAllOffers)  showAllOffers.checked  = false;
      currentSort.col = null;
      currentSort.asc = true;
      sortHeaders.forEach(function (h) { h.classList.remove("sort-asc", "sort-desc"); });
      try { sessionStorage.removeItem(STATE_KEY); } catch (e) {}
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
      if (col === "cv_score") {
        va = parseFloat(a.dataset.cvScore) || 0;
        vb = parseFloat(b.dataset.cvScore) || 0;
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

  // ── State persistence (sessionStorage) ─────────────────────────────

  var STATE_KEY = "jh-dash-state";

  function saveState() {
    try {
      sessionStorage.setItem(STATE_KEY, JSON.stringify({
        status:         filterStatus   ? filterStatus.value    : "",
        source:         filterSource   ? filterSource.value    : "",
        domain:         filterDomain   ? filterDomain.value    : "",
        location:       filterLocation ? filterLocation.value  : "",
        contract:       filterContract ? filterContract.value  : "",
        company:        filterCompany  ? filterCompany.value   : "",
        search:         filterSearch   ? filterSearch.value    : "",
        showRecruiters: showRecruiters ? showRecruiters.checked : false,
        showAll:        showAllOffers  ? showAllOffers.checked  : false,
        sortCol:        currentSort.col,
        sortAsc:        currentSort.asc,
        page:           currentPage,
      }));
    } catch (e) {}
  }

  function restoreState(state) {
    if (!state) return false;
    if (filterStatus   && state.status   !== undefined) filterStatus.value    = state.status;
    if (filterSource   && state.source   !== undefined) filterSource.value    = state.source;
    if (filterDomain   && state.domain   !== undefined) filterDomain.value    = state.domain;
    if (filterCompany  && state.company  !== undefined) filterCompany.value   = state.company;
    if (filterLocation && state.location !== undefined) filterLocation.value  = state.location;
    if (filterContract && state.contract !== undefined) filterContract.value  = state.contract;
    if (filterSearch   && state.search   !== undefined) filterSearch.value    = state.search;
    if (showRecruiters && state.showRecruiters !== undefined) showRecruiters.checked = state.showRecruiters;
    if (showAllOffers  && state.showAll        !== undefined) showAllOffers.checked  = state.showAll;
    if (state.sortCol) {
      currentSort.col = state.sortCol;
      currentSort.asc = state.sortAsc !== false;
      sortHeaders.forEach(function (h) { h.classList.remove("sort-asc", "sort-desc"); });
      var activeHdr = document.querySelector('.sortable[data-col="' + state.sortCol + '"]');
      if (activeHdr) activeHdr.classList.add(currentSort.asc ? "sort-asc" : "sort-desc");
      sortTable(state.sortCol, currentSort.asc);
    } else {
      applyFilters();
    }
    if (state.page > 0) {
      currentPage = state.page;
      renderPage();
      saveState();
    }
    return true;
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

  // ── CV rematch ────────────────────────────────────────────

  var cvStatusMsg      = document.getElementById("cv-upload-status");
  var btnRematchCv     = document.getElementById("btn-rematch-cv");
  var btnRematchClaude = document.getElementById("btn-rematch-claude");
  var cvMatchProgress  = document.getElementById("cv-match-progress");
  var cvProgressFill   = document.getElementById("cv-progress-fill");
  var cvProgressText   = document.getElementById("cv-progress-text");

  var _matchingInterval = null;  // setInterval handle for polling

  function cvSetStatus(msg, isError) {
    if (!cvStatusMsg) return;
    cvStatusMsg.textContent = msg;
    cvStatusMsg.style.color = isError ? "var(--accent-red, #ef4444)" : "var(--accent-green, #22c55e)";
  }

  function _setMatchButtons(disabled) {
    if (btnRematchCv)     btnRematchCv.disabled     = disabled;
    if (btnRematchClaude) btnRematchClaude.disabled = disabled;
  }

  function _showProgress(show) {
    if (cvMatchProgress) {
      if (show) { cvMatchProgress.classList.remove("hidden"); }
      else      { cvMatchProgress.classList.add("hidden"); }
    }
  }

  function _updateProgressBar(scored, total) {
    var pct = total > 0 ? Math.min(100, Math.round(scored / total * 100)) : 0;
    if (cvProgressFill) cvProgressFill.style.width = pct + "%";
    if (cvProgressText) cvProgressText.textContent = scored + " / " + total + " offres (" + pct + "%)";
  }

  function _stopPolling() {
    if (_matchingInterval) {
      clearInterval(_matchingInterval);
      _matchingInterval = null;
    }
  }

  function _pollMatchingStatus() {
    fetch("/api/cv/matching-status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var t = TRANSLATIONS[currentLang] || TRANSLATIONS.fr;
        if (data.status === "done") {
          _stopPolling();
          _updateProgressBar(data.scored || 0, data.total || data.scored || 1);
          cvSetStatus(t.cv_match_done, false);
          setTimeout(function () { location.reload(); }, 1000);
        } else if (data.status === "error") {
          _stopPolling();
          _showProgress(false);
          _setMatchButtons(false);
          cvSetStatus(t.cv_error + (data.error || "unknown"), true);
        } else if (data.status === "running") {
          _updateProgressBar(data.scored || 0, data.total || 0);
        } else if (data.status === "none") {
          // No task — stop polling silently
          _stopPolling();
          _showProgress(false);
          _setMatchButtons(false);
        }
      })
      .catch(function () { /* network hiccup — keep polling */ });
  }

  function _startMatchingPoll(url) {
    var t = TRANSLATIONS[currentLang] || TRANSLATIONS.fr;
    _setMatchButtons(true);
    _showProgress(true);
    if (cvProgressFill) cvProgressFill.style.width = "0%";
    if (cvProgressText) cvProgressText.textContent = "";
    cvSetStatus(t.cv_match_started, false);

    fetch(url, { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok && data.status !== "already_running") {
          _showProgress(false);
          _setMatchButtons(false);
          cvSetStatus(t.cv_error + (data.error || "unknown"), true);
          return;
        }
        if (data.status === "already_running") {
          cvSetStatus(t.cv_match_running, false);
          _updateProgressBar(data.scored || 0, data.total || 0);
        }
        // Start polling regardless (started or already_running)
        _stopPolling();
        _pollMatchingStatus();  // immediate first poll
        _matchingInterval = setInterval(_pollMatchingStatus, 2000);
      })
      .catch(function (err) {
        _showProgress(false);
        _setMatchButtons(false);
        cvSetStatus(t.cv_error + err, true);
      });
  }

  if (btnRematchCv) {
    btnRematchCv.addEventListener("click", function () {
      _startMatchingPoll("/api/cv/rematch");
    });
  }

  if (btnRematchClaude) {
    btnRematchClaude.addEventListener("click", function () {
      _startMatchingPoll("/api/cv/rematch?method=claude&force=true");
    });
  }

  // ── Initial render ─────────────────────────────────────────────────
  var tableEl = document.getElementById("offers-table");
  var hasCv   = tableEl && tableEl.dataset.hasCv === "true";
  var savedState = null;
  try { savedState = JSON.parse(sessionStorage.getItem(STATE_KEY) || "null"); } catch (e) {}

  if (savedState) {
    restoreState(savedState);
  } else if (hasCv) {
    currentSort.col = "cv_score";
    currentSort.asc = false;
    var cvHdr = document.querySelector('.sortable[data-col="cv_score"]');
    if (cvHdr) cvHdr.classList.add("sort-desc");
    sortTable("cv_score", false);
  } else {
    applyFilters();
  }
  applyLang(currentLang);

  // Auto-resume polling if a matching job is already running (e.g. page refresh)
  if (hasCv) {
    fetch("/api/cv/matching-status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.status === "running") {
          _setMatchButtons(true);
          _showProgress(true);
          _updateProgressBar(data.scored || 0, data.total || 0);
          _stopPolling();
          _matchingInterval = setInterval(_pollMatchingStatus, 2000);
        }
      })
      .catch(function () {});
  }

})();
