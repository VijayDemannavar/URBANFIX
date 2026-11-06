/**
 * CivicAI – main.js
 * Client-side behaviour for citizen form, admin dashboard, and detail page.
 * No dependencies – vanilla JS only.
 */

"use strict";

/* ── Helpers ──────────────────────────────────────────────────────── */
function $(sel, ctx) { return (ctx || document).querySelector(sel); }
function $$(sel, ctx) { return Array.from((ctx || document).querySelectorAll(sel)); }
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

function showAlert(msg, type, container) {
  const div = document.createElement("div");
  div.className = `alert alert-${type}`;
  div.textContent = msg;
  if (container) { container.prepend(div); setTimeout(() => div.remove(), 6000); }
}

/* ── Image preview / file drop ────────────────────────────────────── */
function initFileDrop() {
  const drop    = $("#image-drop");
  const input   = $("#image-input");
  const preview = $("#image-preview");
  const previewImg = preview && preview.querySelector("img");
  const label   = drop && drop.querySelector(".drop-label");

  if (!drop || !input) return;

  drop.addEventListener("click", () => input.click());

  drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("drag-over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("drag-over"));
  drop.addEventListener("drop", e => {
    e.preventDefault();
    drop.classList.remove("drag-over");
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      handleFile(input.files[0]);
    }
  });

  input.addEventListener("change", () => {
    if (input.files.length) handleFile(input.files[0]);
  });

  function handleFile(file) {
    const MAX = 5 * 1024 * 1024;
    const TYPES = ["image/png","image/jpeg","image/gif","image/webp"];
    const errEl = $("#image-error");

    if (!TYPES.includes(file.type)) {
      if (errEl) { errEl.textContent = "Only PNG, JPG, GIF, WEBP files are allowed."; errEl.classList.add("show"); }
      input.value = "";
      return;
    }
    if (file.size > MAX) {
      if (errEl) { errEl.textContent = "Image must be under 5 MB."; errEl.classList.add("show"); }
      input.value = "";
      return;
    }
    if (errEl) errEl.classList.remove("show");

    const reader = new FileReader();
    reader.onload = ev => {
      if (previewImg) previewImg.src = ev.target.result;
      if (preview) preview.style.display = "block";
      if (label) label.innerHTML = `<strong>${esc(file.name)}</strong> (${(file.size/1024).toFixed(1)} KB) – click to change`;
    };
    reader.readAsDataURL(file);
  }
}

/* ── Character counter ────────────────────────────────────────────── */
function initCharCounters() {
  $$("textarea[maxlength], input[maxlength]").forEach(el => {
    const max = parseInt(el.getAttribute("maxlength"), 10);
    if (!max) return;
    const counter = document.createElement("div");
    counter.className = "char-counter";
    el.parentNode.appendChild(counter);
    function update() {
      const left = max - el.value.length;
      counter.textContent = `${el.value.length} / ${max}`;
      counter.className = "char-counter" + (left < 20 ? " warn" : "") + (left < 0 ? " over" : "");
    }
    el.addEventListener("input", update);
    update();
  });
}

/* ── Complaint form validation ────────────────────────────────────── */
function initComplaintForm() {
  const form = $("#complaint-form");
  if (!form) return;

  form.addEventListener("submit", function(e) {
    let valid = true;

    $$(".field-error", form).forEach(el => el.classList.remove("show"));
    $$("input, textarea, select", form).forEach(el => el.classList.remove("error"));

    function fail(fieldId, msg) {
      const el = form.querySelector(`#${fieldId}`);
      const err = form.querySelector(`#${fieldId}-error`);
      if (el)  el.classList.add("error");
      if (err) { err.textContent = msg; err.classList.add("show"); }
      if (valid) el && el.focus();   // focus first error
      valid = false;
    }

    const title = $("#title");
    const desc  = $("#description");
    const cat   = $("#category");

    if (!title || !title.value.trim())       fail("title",       "Title is required.");
    else if (title.value.trim().length < 10) fail("title",       "Title must be at least 10 characters.");

    if (!desc || !desc.value.trim())         fail("description", "Description is required.");
    else if (desc.value.trim().length < 20)  fail("description", "Description must be at least 20 characters.");

    if (!cat || !cat.value)                  fail("category",    "Please select a category.");

    const lat  = $("#latitude");
    const lon  = $("#longitude");
    if (lat && lat.value !== "") {
      const v = parseFloat(lat.value);
      if (isNaN(v) || v < -90 || v > 90) fail("latitude", "Latitude must be between -90 and 90.");
    }
    if (lon && lon.value !== "") {
      const v = parseFloat(lon.value);
      if (isNaN(v) || v < -180 || v > 180) fail("longitude", "Longitude must be between -180 and 180.");
    }

    if (!valid) e.preventDefault();
  });
}

/* ── Admin dashboard: live search + filter ────────────────────────── */
function initDashboardFilters() {
  const searchInput    = $("#search-input");
  const catFilter      = $("#filter-category");
  const statusFilter   = $("#filter-status");
  const priorityFilter = $("#filter-priority");
  const clearBtn       = $("#clear-filters");
  const tableBody      = $("#complaints-tbody");
  const countLabel     = $("#results-count");

  if (!tableBody) return;

  const rows = $$("tr[data-cid]", tableBody);

  function applyFilters() {
    const q        = searchInput    ? searchInput.value.toLowerCase() : "";
    const cat      = catFilter      ? catFilter.value      : "";
    const status   = statusFilter   ? statusFilter.value   : "";
    const priority = priorityFilter ? priorityFilter.value : "";
    let visible    = 0;

    rows.forEach(row => {
      const text   = row.dataset.text     || "";
      const rCat   = row.dataset.cat      || "";
      const rStat  = row.dataset.status   || "";
      const rPrio  = row.dataset.priority || "";

      const matchQ  = !q        || text.includes(q);
      const matchC  = !cat      || rCat  === cat;
      const matchS  = !status   || rStat === status;
      const matchP  = !priority || rPrio === priority;

      const show = matchQ && matchC && matchS && matchP;
      row.style.display = show ? "" : "none";
      if (show) visible++;
    });

    if (countLabel) {
      countLabel.textContent = `Showing ${visible} of ${rows.length} complaints`;
    }

    // empty state
    const empty = $("#empty-state");
    if (empty) empty.style.display = visible === 0 ? "" : "none";
  }

  if (searchInput)    searchInput.addEventListener("input",   applyFilters);
  if (catFilter)      catFilter.addEventListener("change",    applyFilters);
  if (statusFilter)   statusFilter.addEventListener("change", applyFilters);
  if (priorityFilter) priorityFilter.addEventListener("change", applyFilters);

  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      if (searchInput)    searchInput.value    = "";
      if (catFilter)      catFilter.value      = "";
      if (statusFilter)   statusFilter.value   = "";
      if (priorityFilter) priorityFilter.value = "";
      applyFilters();
    });
  }

  applyFilters();   // run once on load
}

/* ── GPS geolocation capture ──────────────────────────────────────── */
function initGeolocate() {
  const btn    = $("#use-location");
  const status = $("#geo-status");
  const latEl  = $("#latitude");
  const lonEl  = $("#longitude");

  // Hide button entirely if Geolocation API is unavailable (e.g. insecure context)
  if (!btn) return;
  if (!navigator.geolocation) {
    btn.style.display = "none";
    return;
  }

  btn.addEventListener("click", function () {
    if (status) status.textContent = "Detecting location…";
    btn.disabled = true;

    navigator.geolocation.getCurrentPosition(
      function (pos) {
        const lat = pos.coords.latitude.toFixed(6);
        const lon = pos.coords.longitude.toFixed(6);
        if (latEl) { latEl.value = lat; latEl.dispatchEvent(new Event("input")); }
        if (lonEl) { lonEl.value = lon; lonEl.dispatchEvent(new Event("input")); }
        if (status) status.textContent = "✓ Location captured (" + lat + ", " + lon + ")";
        btn.disabled = false;
      },
      function (err) {
        const messages = {
          1: "Location access denied. Please enter coordinates manually.",
          2: "Location unavailable. Please enter coordinates manually.",
          3: "Location request timed out. Please try again.",
        };
        if (status) status.textContent = messages[err.code] || "Location error.";
        btn.disabled = false;
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
  });
}

/* ── Complaint ID copy ────────────────────────────────────────────── */
function initCopyId() {
  const box = $(".complaint-id-box");
  if (!box) return;
  box.title = "Click to copy";
  box.addEventListener("click", () => {
    const id = box.dataset.id || box.textContent.trim();
    navigator.clipboard.writeText(id).then(() => {
      const orig = box.textContent;
      box.textContent = "Copied!";
      setTimeout(() => { box.textContent = orig; }, 1500);
    });
  });
}

/* ── Column sort (client-side for small tables) ───────────────────── */
function initTableSort() {
  $$("th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const table = th.closest("table");
      const tbody = table.querySelector("tbody");
      if (!tbody) return;

      const col    = parseInt(th.dataset.col, 10);
      const isAsc  = !th.classList.contains("sort-asc");

      $$("th.sortable", table).forEach(h => h.classList.remove("sort-asc","sort-desc"));
      th.classList.add(isAsc ? "sort-asc" : "sort-desc");

      const rows = Array.from(tbody.querySelectorAll("tr[data-cid]"));
      rows.sort((a, b) => {
        const aVal = (a.cells[col] || {}).textContent.trim().toLowerCase();
        const bVal = (b.cells[col] || {}).textContent.trim().toLowerCase();
        return isAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      });
      rows.forEach(r => tbody.appendChild(r));
    });
  });
}

/* ── Init ─────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  initFileDrop();
  initCharCounters();
  initComplaintForm();
  initDashboardFilters();
  initCopyId();
  initTableSort();
  initGeolocate();
});
