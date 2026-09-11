from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
from typing import Iterable, Mapping

from .catalog import CatalogEntry
from .runtime_table import RuntimeRow


def _identity(kind: str, key: str) -> str:
    return f"{kind}\t{key}"


_DIALOGUE_FUNCTION_RE = re.compile(r"^dialogue:(0x[0-9a-fA-F]+):")


def _speaker_for_entry(
    entry: CatalogEntry, speaker_map: Mapping[str, object] | None
) -> str:
    if entry.kind != "dialogue":
        return ""
    if speaker_map:
        for lookup_key in (_identity(entry.kind, entry.key), entry.key):
            value = speaker_map.get(lookup_key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    match = _DIALOGUE_FUNCTION_RE.match(entry.key)
    if match:
        return f"Unresolved · usecode 0x{int(match.group(1), 16):04X}"
    return "Unresolved"


def _script_json(value: object) -> str:
    # A source string must not be able to close the data script element.
    return json.dumps(value, ensure_ascii=False, indent=2).replace("</", "<\\/")


def _review_records(
    entries: list[CatalogEntry],
    rows: Iterable[RuntimeRow],
    *,
    model: str,
    prompt_version: str,
    audit: Mapping[str, object] | None,
    speaker_map: Mapping[str, object] | None,
) -> tuple[list[dict[str, object]], str]:
    rows_by_identity = {(row.kind, row.key): row for row in rows}
    issues_by_identity: dict[tuple[str, str], list[str]] = {}
    if audit:
        raw_issues = audit.get("issues", [])
        if isinstance(raw_issues, list):
            for issue in raw_issues:
                if not isinstance(issue, Mapping):
                    continue
                key = issue.get("key")
                message = issue.get("message")
                if not isinstance(key, str) or not isinstance(message, str):
                    continue
                matching = [
                    (entry.kind, entry.key)
                    for entry in entries
                    if entry.key == key
                ]
                for identity in matching:
                    issues_by_identity.setdefault(identity, []).append(message)

    records: list[dict[str, object]] = []
    fingerprints: list[str] = []
    for entry in entries:
        row = rows_by_identity.get((entry.kind, entry.key))
        zh = row.zh if row is not None else ""
        issues = list(dict.fromkeys(issues_by_identity.get((entry.kind, entry.key), [])))
        status = (
            "approved"
            if row is not None and not issues and (zh.strip() or not entry.source.strip())
            else "needs-review"
        )
        records.append(
            {
                "kind": entry.kind,
                "key": entry.key,
                "source_sha256": entry.source_sha256,
                "source": entry.source,
                "context": entry.context,
                "origin": entry.origin,
                "protected_tokens": list(entry.protected_tokens),
                "speaker": _speaker_for_entry(entry, speaker_map),
                "candidate_zh": zh,
                "zh": zh,
                "status": status,
                "issues": issues,
                "suggested_zh": zh,
                "model": model,
                "prompt_version": prompt_version,
            }
        )
        fingerprints.append(
            "\t".join((entry.kind, entry.key, entry.source_sha256, zh))
        )
    fingerprint = hashlib.sha256("\n".join(fingerprints).encode("utf-8")).hexdigest()
    return records, fingerprint


def build_review_html(
    entries: Iterable[CatalogEntry],
    rows: Iterable[RuntimeRow],
    *,
    model: str,
    prompt_version: str,
    audit: Mapping[str, object] | None = None,
    speaker_map: Mapping[str, object] | None = None,
) -> str:
    """Build an offline editable review page for a catalog/table pair."""

    ordered_entries = list(entries)
    records, fingerprint = _review_records(
        ordered_entries,
        rows,
        model=model,
        prompt_version=prompt_version,
        audit=audit,
        speaker_map=speaker_map,
    )
    data = {"fingerprint": fingerprint, "records": records}
    title = "U6 Translation Review"
    css = r"""
      :root { color-scheme: light; --border:#d7dce2; --muted:#5f6b76; --blue:#eaf4ff; --yellow:#fff5cf; --green:#e9f8ed; }
      * { box-sizing: border-box; }
      body { font: 14px system-ui, sans-serif; margin: 0; color: #20252b; background: #f5f7f9; }
      header { position: sticky; top: 0; z-index: 2; padding: 1rem 1.5rem; background: #fff; border-bottom: 1px solid var(--border); box-shadow: 0 1px 4px #0001; }
      h1 { margin: 0 0 .3rem; font-size: 1.35rem; }
      .meta, .help, .counts { color: var(--muted); margin: .25rem 0; }
      .toolbar { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; margin-top: .75rem; }
      input[type=search], select, button { font: inherit; padding: .4rem .55rem; border: 1px solid #aeb8c2; border-radius: .3rem; background: #fff; }
      button { cursor: pointer; }
      button.primary { color: #fff; background: #1261a0; border-color: #1261a0; }
      main { padding: 1rem 1.5rem 3rem; }
      table { border-collapse: collapse; width: 100%; background: #fff; }
      th, td { border: 1px solid var(--border); padding: .5rem; text-align: left; vertical-align: top; }
      th { position: sticky; top: 133px; z-index: 1; background: #eef1f4; }
      tr[data-status=needs-review] { background: var(--yellow); }
      tr[data-status=approved] { background: #fff; }
      tr[data-hidden=true] { display: none; }
      td.kind { white-space: nowrap; font-weight: 600; }
      td.key { min-width: 14rem; }
      td.speaker { min-width: 10rem; font-weight: 600; }
      td.source { min-width: 24rem; white-space: pre-wrap; }
      td.translation { min-width: 24rem; background: var(--blue); }
      td.translation textarea { width: 100%; min-height: 4.5rem; resize: vertical; font: 1rem/1.45 system-ui, sans-serif; padding: .4rem; }
      td.review { min-width: 12rem; }
      td.review label { display: block; white-space: nowrap; }
      .status { display: inline-block; margin-top: .35rem; padding: .15rem .35rem; border-radius: .25rem; font-weight: 600; }
      [data-status=approved] .status { color: #176b2b; background: var(--green); }
      [data-status=needs-review] .status { color: #805800; background: #ffe59a; }
      .issues { color: #a33; margin-top: .4rem; font-size: .85rem; }
      code { font-size: .8rem; overflow-wrap: anywhere; }
      pre { margin: 0; font: inherit; white-space: pre-wrap; }
      .pagination { display: flex; align-items: center; justify-content: center; gap: .65rem; margin: 1rem 0; }
      .pagination button:disabled { cursor: not-allowed; opacity: .45; }
      @media (max-width: 900px) { th { top: 190px; } main { padding: .5rem; } header { padding: .75rem; } td.source, td.translation { min-width: 16rem; } }
    """
    rows_html: list[str] = []
    for index, record in enumerate(records):
        source = html.escape(str(record["source"]))
        zh = html.escape(str(record["zh"]))
        issues = record.get("issues", [])
        issue_html = "".join(f"<div>{html.escape(str(issue))}</div>" for issue in issues)
        status = str(record["status"])
        identity = html.escape(_identity(str(record["kind"]), str(record["key"])), quote=True)
        rows_html.append(
            f'<tr data-index="{index}" data-identity="{identity}" data-status="{status}" data-hidden="false">'
            f'<td class="kind">{html.escape(str(record["kind"]))}</td>'
            f'<td class="key"><code>{html.escape(str(record["key"]))}</code></td>'
            f'<td class="speaker">{html.escape(str(record["speaker"])) or "—"}</td>'
            f'<td class="source"><div><small>{html.escape(str(record["context"]))}</small></div><pre>{source}</pre></td>'
            f'<td class="translation"><textarea data-field="zh" aria-label="Chinese translation">{zh}</textarea></td>'
            f'<td class="review"><label><input type="checkbox" data-field="needs"'
            f'{" checked" if status == "needs-review" else ""}> Needs modification</label>'
            f'<span class="status">{"Needs modification" if status == "needs-review" else "Accepted"}</span>'
            f'<div class="issues">{issue_html}</div></td></tr>'
        )

    script_data = _script_json(data)
    script = r"""
      const reviewData = __REVIEW_DATA__;
      const rows = reviewData.records.map(record => ({...record}));
      const storageKey = `u6-translation-review:${reviewData.fingerprint}`;
      const tableRows = [...document.querySelectorAll('tbody tr')];
      const search = document.querySelector('#search');
      const kindFilter = document.querySelector('#kind-filter');
      const statusFilter = document.querySelector('#status-filter');
      const visibleCount = document.querySelector('#visible-count');
      const acceptedCount = document.querySelector('#accepted-count');
      const needsCount = document.querySelector('#needs-count');
      const pageInfo = document.querySelector('#page-info');
      const pagePrev = document.querySelector('#page-prev');
      const pageNext = document.querySelector('#page-next');
      const pageInfoBottom = document.querySelector('#page-info-bottom');
      const pagePrevBottom = document.querySelector('#page-prev-bottom');
      const pageNextBottom = document.querySelector('#page-next-bottom');
      const pageSize = 50;
      let currentPage = 1;

      function stateFor(index) {
        return rows[index];
      }

      function applyRow(rowElement) {
        const index = Number(rowElement.dataset.index);
        const record = stateFor(index);
        const needs = record.status === 'needs-review';
        rowElement.dataset.status = record.status;
        rowElement.querySelector('[data-field=zh]').value = record.zh;
        rowElement.querySelector('[data-field=needs]').checked = needs;
        rowElement.querySelector('.status').textContent = needs ? 'Needs modification' : 'Accepted';
      }

      function refreshCounts() {
        const query = search.value.trim().toLowerCase();
        const kind = kindFilter.value;
        const status = statusFilter.value;
        let visible = 0;
        let accepted = 0;
        let needs = 0;
        tableRows.forEach(rowElement => {
          const index = Number(rowElement.dataset.index);
          const record = stateFor(index);
          const matchesSearch = !query || `${record.kind} ${record.key} ${record.speaker} ${record.source} ${record.zh}`.toLowerCase().includes(query);
          const matchesKind = kind === 'all' || record.kind === kind;
          const matchesStatus = status === 'all' || record.status === status;
          if (matchesSearch && matchesKind && matchesStatus) visible++;
          if (record.status === 'approved') accepted++;
          else needs++;
        });
        const matchingRows = tableRows.filter(rowElement => {
          const record = stateFor(Number(rowElement.dataset.index));
          const matchesSearch = !query || `${record.kind} ${record.key} ${record.speaker} ${record.source} ${record.zh}`.toLowerCase().includes(query);
          const matchesKind = kind === 'all' || record.kind === kind;
          const matchesStatus = status === 'all' || record.status === status;
          return matchesSearch && matchesKind && matchesStatus;
        });
        const pageCount = Math.max(1, Math.ceil(matchingRows.length / pageSize));
        currentPage = Math.min(currentPage, pageCount);
        const first = (currentPage - 1) * pageSize;
        const pageRows = new Set(matchingRows.slice(first, first + pageSize));
        tableRows.forEach(rowElement => {
          rowElement.dataset.hidden = pageRows.has(rowElement) ? 'false' : 'true';
        });
        visibleCount.textContent = String(visible);
        acceptedCount.textContent = String(accepted);
        needsCount.textContent = String(needs);
        const pageText = matchingRows.length
          ? `Page ${currentPage} / ${pageCount} · ${first + 1}-${Math.min(first + pageSize, matchingRows.length)} of ${matchingRows.length}`
          : 'Page 0 / 0 · 0 matching';
        pageInfo.textContent = pageText;
        pageInfoBottom.textContent = pageText;
        const previousDisabled = currentPage <= 1 || !matchingRows.length;
        const nextDisabled = currentPage >= pageCount || !matchingRows.length;
        pagePrev.disabled = previousDisabled;
        pagePrevBottom.disabled = previousDisabled;
        pageNext.disabled = nextDisabled;
        pageNextBottom.disabled = nextDisabled;
      }

      function saveDraft() {
        localStorage.setItem(storageKey, JSON.stringify(rows.map(record => ({zh: record.zh, status: record.status}))));
        document.querySelector('#save-state').textContent = 'Draft saved locally';
      }

      function loadDraft() {
        try {
          const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
          if (!Array.isArray(saved) || saved.length !== rows.length) return;
          saved.forEach((value, index) => {
            if (value && typeof value.zh === 'string' && ['approved', 'needs-review'].includes(value.status)) {
              rows[index].zh = value.zh;
              rows[index].status = value.status;
            }
          });
        } catch (_) { /* Ignore an unavailable or malformed browser draft. */ }
      }

      function downloadReview() {
        const content = rows.map(record => JSON.stringify({
          kind: record.kind, key: record.key, source_sha256: record.source_sha256,
          speaker: record.speaker,
          zh: record.zh, status: record.status, issues: record.issues,
          suggested_zh: record.candidate_zh, model: record.model,
          prompt_version: record.prompt_version
        }, null, 0)).join('\n') + '\n';
        const blob = new Blob([content], {type: 'application/x-ndjson;charset=utf-8'});
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'u6_review.jsonl';
        link.click();
        URL.revokeObjectURL(link.href);
        document.querySelector('#save-state').textContent = 'Review JSONL downloaded';
      }

      document.querySelector('#save').addEventListener('click', saveDraft);
      document.querySelector('#download').addEventListener('click', downloadReview);
      function previousPage() {
        if (currentPage > 1) { currentPage--; refreshCounts(); window.scrollTo({top: 0, behavior: 'smooth'}); }
      }
      function nextPage() {
        currentPage++; refreshCounts(); window.scrollTo({top: 0, behavior: 'smooth'});
      }
      pagePrev.addEventListener('click', previousPage);
      pagePrevBottom.addEventListener('click', previousPage);
      pageNext.addEventListener('click', nextPage);
      pageNextBottom.addEventListener('click', nextPage);
      document.querySelector('#reset').addEventListener('click', () => {
        localStorage.removeItem(storageKey);
        window.location.reload();
      });
      [search, kindFilter, statusFilter].forEach(element => element.addEventListener('input', () => { currentPage = 1; refreshCounts(); }));
      tableRows.forEach(rowElement => {
        const index = Number(rowElement.dataset.index);
        rowElement.querySelector('[data-field=zh]').addEventListener('input', event => {
          rows[index].zh = event.target.value;
          saveDraft();
          refreshCounts();
        });
        rowElement.querySelector('[data-field=needs]').addEventListener('change', event => {
          rows[index].status = event.target.checked ? 'needs-review' : 'approved';
          applyRow(rowElement);
          saveDraft();
          refreshCounts();
        });
      });
      loadDraft();
      tableRows.forEach(applyRow);
      refreshCounts();
    """.replace("__REVIEW_DATA__", script_data)
    kinds = sorted({str(record["kind"]) for record in records})
    kind_options = "".join(f'<option value="{html.escape(kind, quote=True)}">{html.escape(kind)}</option>' for kind in kinds)
    return (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title><style>{css}</style></head><body><header>'
        f'<h1>Ultima VI Traditional Chinese Translation Review</h1>'
        '<div class="meta">Edit each translation directly. Every row is <b>accepted by default</b>; '
        'check “Needs modification” only when it requires correction.</div>'
        f'<div class="meta">Model: <b>{html.escape(model)}</b> · Prompt: <b>{html.escape(prompt_version)}</b> · '
        f'Rows: <b>{len(records)}</b> · Fingerprint: <code>{fingerprint}</code></div>'
        '<div class="toolbar"><input id="search" type="search" placeholder="Search English, Chinese, key...">'
        '<label>Kind <select id="kind-filter"><option value="all">All</option>' + kind_options + '</select></label>'
        '<label>Status <select id="status-filter"><option value="all">All</option>'
        '<option value="approved">Accepted</option><option value="needs-review">Needs modification</option></select></label>'
        '<button id="save">Save draft</button><button id="reset">Reset draft</button>'
        '<button id="download" class="primary">Download review JSONL</button>'
        '<span id="save-state" class="help">Changes auto-save in this browser.</span></div>'
        '<div class="counts">Matching: <b id="visible-count">0</b> · Accepted: <b id="accepted-count">0</b> · '
        'Needs modification: <b id="needs-count">0</b></div></header><main>'
        '<div class="pagination"><button id="page-prev" disabled>Previous</button>'
        '<span id="page-info">Page 1 / 1</span> · <b id="page-size">50</b> entries/page'
        '<button id="page-next" disabled>Next</button></div>'
        '<table><thead><tr><th>Kind</th><th>Key</th><th>Speaker</th><th>English</th>'
        '<th>Traditional Chinese (editable)</th><th>Review</th>'
        '</tr></thead><tbody>' + "".join(rows_html) + '</tbody></table>'
        '<div class="pagination"><button id="page-prev-bottom" disabled>Previous</button>'
        '<span id="page-info-bottom">Page 1 / 1</span> · <b>50</b> entries/page'
        '<button id="page-next-bottom" disabled>Next</button></div>'
        '</main><script>' + script + '</script></body></html>'
    )


def write_review_html(
    path: Path,
    entries: Iterable[CatalogEntry],
    rows: Iterable[RuntimeRow],
    *,
    model: str,
    prompt_version: str,
    audit: Mapping[str, object] | None = None,
    speaker_map: Mapping[str, object] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_review_html(
            entries,
            rows,
            model=model,
            prompt_version=prompt_version,
            audit=audit,
            speaker_map=speaker_map,
        ),
        encoding="utf-8",
    )
