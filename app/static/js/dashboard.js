/**
 * JobHunter Dashboard - AJAX tracking, server-side filtering & pagination.
 * Filters/sorting submit a GET form; pagination uses server-rendered links.
 * AJAX save, favorites, notes, CV matching, CSV export remain client-side.
 */

(function () {
  "use strict";

  // ── Translations ────────────────────────────────────────────────────

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
      filter_favorites:   "Favoris uniquement",
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
      filter_favorites:   "Favorites only",
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

    var els = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < els.length; i++) {
      var key = els[i].getAttribute("data-i18n");
      if (t[key] !== undefined) els[i].textContent = t[key];
    }

    var pls = document.querySelectorAll("[data-i18n-placeholder]");
    for (var j = 0; j < pls.length; j++) {
      var pkey = pls[j].getAttribute("data-i18n-placeholder");
      if (t[pkey] !== undefined) pls[j].placeholder = t[pkey];
    }

    translateStatusSelects(lang);
  }

  function translateStatusSelects(lang) {
    var labels = STATUS_LABELS[lang] || STATUS_LABELS.en;
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

  document.addEventListener("jh-lang-change", function (e) {
    applyLang(e.detail.lang);
  });

  // ── Persist dashboard params in sessionStorage ─────────────────────
  // On load: if URL has query params, save them; if not, restore from session.
  (function persistDashboardParams() {
    var search = window.location.search;
    if (search && search !== "?") {
      sessionStorage.setItem("dashboard_params", search);
    } else {
      var saved = sessionStorage.getItem("dashboard_params");
      if (saved) {
        window.location.replace(window.location.pathname + saved);
        return; // page will reload
      }
    }
  })();

  // ── Guard: early return if no table ─────────────────────────────────

  var tbody = document.querySelector("#offers-table tbody");
  if (!tbody) {
    applyLang(currentLang);
    return;
  }

  // ── Stats counters (optimistic UI updates) ──────────────────────────

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
    fetch("/api/tracking/" + offerId, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res.ok) {
          console.error("Save failed", res.error);
          return;
        }
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
    var target = e.target;
    var row = target.closest(".offer-row");
    if (!row) return;
    var offerId = row.dataset.offerId;

    // Status dropdown
    if (target.dataset.field === "status") {
      var oldStatus = row.dataset.status;
      var newStatus = target.value;

      if (oldStatus === "Interview" && newStatus !== "Interview") counts.interviews--;
      if (oldStatus !== "Interview" && newStatus === "Interview") counts.interviews++;

      renderStats();
      row.dataset.status = newStatus;
      target.className = "status-select status-color-" +
        newStatus.toLowerCase().replace(/ /g, "-");

      saveTracking(offerId, { status: newStatus });
      return;
    }

    // Checkboxes (cv_sent, follow_up_done)
    if (target.classList.contains("tracking-checkbox")) {
      var field   = target.dataset.field;
      var checked = target.checked;

      if (field === "cv_sent")       counts.cv += checked ? 1 : -1;
      if (field === "follow_up_done") counts.fu += checked ? 1 : -1;

      renderStats();

      var payload = {};
      payload[field] = checked;
      saveTracking(offerId, payload);
      return;
    }
  });

  // ── Event delegation: favorite star toggle ────────────────────────

  tbody.addEventListener("click", function (e) {
    var btn = e.target.closest(".btn-fav");
    if (!btn) return;
    var row = btn.closest(".offer-row");
    if (!row) return;
    var offerId = row.dataset.offerId;

    var isFav = row.dataset.favorite === "1";
    row.dataset.favorite = isFav ? "0" : "1";
    btn.textContent = isFav ? "\u2606" : "\u2605";
    btn.classList.toggle("fav-active", !isFav);

    fetch("/api/tracking/" + offerId + "/favorite", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res.ok) {
          row.dataset.favorite = isFav ? "1" : "0";
          btn.textContent = isFav ? "\u2605" : "\u2606";
          btn.classList.toggle("fav-active", isFav);
        }
      })
      .catch(function () {
        row.dataset.favorite = isFav ? "1" : "0";
        btn.textContent = isFav ? "\u2605" : "\u2606";
        btn.classList.toggle("fav-active", isFav);
      });
  });

  // ── Event delegation: quick apply button ─────────────────────────────

  tbody.addEventListener("click", function (e) {
    var btn = e.target.closest(".btn-apply");
    if (!btn || btn.disabled) return;
    var row = btn.closest(".offer-row");
    if (!row) return;
    var offerId = row.dataset.offerId;
    var url = btn.getAttribute("data-url");

    // Open the offer URL in a new tab
    window.open(url, "_blank", "noopener,noreferrer");

    // Mark as applied
    btn.disabled = true;
    btn.innerHTML = "\u2026"; // ellipsis while loading

    fetch("/api/tracking/" + offerId + "/apply", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res.ok) {
          btn.innerHTML = "\u2713"; // checkmark
          btn.classList.add("btn-applied");
          row.classList.add("row-applied");
          // Update the row's status + cv_sent
          row.dataset.status = "Applied";
          var statusSel = row.querySelector('[data-field="status"]');
          if (statusSel) {
            statusSel.value = "Applied";
            statusSel.className = "status-select status-color-applied";
          }
          var cvCb = row.querySelector('[data-field="cv_sent"]');
          if (cvCb && !cvCb.checked) {
            cvCb.checked = true;
            counts.cv++;
            renderStats();
          }
          // Update date label
          if (res.tracking && res.tracking.date_sent) {
            var dateLabel = cvCb ? cvCb.closest("td").querySelector(".date-label") : null;
            if (dateLabel) dateLabel.textContent = formatShort(res.tracking.date_sent);
          }
        } else {
          btn.disabled = false;
          btn.innerHTML = "Postuler \u2197";
        }
      })
      .catch(function () {
        btn.disabled = false;
        btn.innerHTML = "Postuler \u2197";
      });
  });

  // ── Event delegation: notes (debounced AJAX) ───────────────────────

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

  // ── Filter form submission ──────────────────────────────────────────

  var filtersForm = document.getElementById("filters-form");

  function submitFilters() {
    if (filtersForm) filtersForm.submit();
  }

  // Select/checkbox filters → submit immediately
  var autoSubmitIds = [
    "filter-status", "filter-source", "filter-domain", "filter-contract",
    "show-all-offers", "show-recruiters", "show-favorites", "filter-cv-sent"
  ];
  autoSubmitIds.forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("change", submitFilters);
  });

  // Text filters → submit on Enter
  var textFilterIds = ["filter-company", "filter-location", "filter-search"];
  textFilterIds.forEach(function (id) {
    var el = document.getElementById(id);
    if (el) {
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          e.preventDefault();
          submitFilters();
        }
      });
    }
  });

  // Reset button → navigate to bare dashboard URL
  var resetBtn = document.getElementById("filters-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", function () {
      sessionStorage.removeItem("dashboard_params");
      window.location.href = window.location.pathname;
    });
  }

  // ── Sort headers → update hidden inputs + submit form ──────────────

  var sortInput = document.getElementById("sort-input");
  var orderInput = document.getElementById("order-input");
  var sortHeaders = document.querySelectorAll(".sortable");

  sortHeaders.forEach(function (th) {
    th.style.cursor = "pointer";
    th.addEventListener("click", function () {
      var col = this.dataset.col;
      var newOrder = this.dataset.newOrder || "asc";

      if (sortInput) sortInput.value = col;
      if (orderInput) orderInput.value = newOrder;
      submitFilters();
    });
  });

  // ── CSV Export (current page) ───────────────────────────────────────

  var exportBtn = document.getElementById("export-csv");
  if (exportBtn) {
    exportBtn.addEventListener("click", exportCSV);
  }

  function exportCSV() {
    var t = TRANSLATIONS[currentLang] || TRANSLATIONS.fr;
    var labels = STATUS_LABELS[currentLang] || STATUS_LABELS.en;

    var headers = [
      t.col_title, t.col_company, t.col_location, t.col_source,
      t.col_date, t.col_score, t.col_status, t.col_cv, t.col_followup,
      t.col_notes, "URL"
    ];

    var rows = [headers];
    var allRows = tbody.querySelectorAll(".offer-row");

    for (var i = 0; i < allRows.length; i++) {
      var row = allRows[i];
      var statusVal = row.dataset.status;
      var viewLink = row.querySelector(".btn-view");

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
        viewLink ? viewLink.href : "",
      ]);
    }

    var csv = rows.map(function (r) {
      return r.map(function (cell) {
        var s = String(cell === null || cell === undefined ? "" : cell);
        if (s.indexOf(",") !== -1 || s.indexOf('"') !== -1 || s.indexOf("\n") !== -1) {
          s = '"' + s.replace(/"/g, '""') + '"';
        }
        return s;
      }).join(",");
    }).join("\n");

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

  var _matchingInterval = null;

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
        _stopPolling();
        _pollMatchingStatus();
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

  applyLang(currentLang);

  // Initialize favorite star styles
  var allRows = Array.from(tbody.querySelectorAll(".offer-row"));
  allRows.forEach(function (row) {
    if (row.dataset.favorite === "1") {
      var favBtn = row.querySelector(".btn-fav");
      if (favBtn) favBtn.classList.add("fav-active");
    }
  });

  // Auto-resume polling if a matching job is already running
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
