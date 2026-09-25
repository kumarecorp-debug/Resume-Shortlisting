/**
 * Candidate Management & Pagination JS
 * Features:
 * - Candidate Status Tracking (new, used, not_used)
 * - Copy = Auto-Mark Used with 5-second Undo Toast
 * - Status Badge Click Popup Menu
 * - Toolbar Filters: All, New, Used, Not Used & Hide Used Checkbox
 * - "Load More" Pagination (25 per page)
 */

let state = {
    searchId: null,
    jobQuery: '',
    mailbox: '',
    offset: 25,
    limit: 25,
    total: 0,
    candidates: [],
    undoTimeout: null,
    lastCopiedItems: []
};

document.addEventListener('DOMContentLoaded', function () {
    const metaContainer = document.getElementById('pagination-meta');
    if (metaContainer) {
        state.searchId = metaContainer.getAttribute('data-search-id') || null;
        state.jobQuery = metaContainer.getAttribute('data-job-query') || '';
        state.mailbox = metaContainer.getAttribute('data-mailbox') || '';
        state.total = parseInt(metaContainer.getAttribute('data-total') || '0', 10);
    }

    applyTableFilters();
});

// ============================================================
// COLUMN COPY FUNCTIONALITY
// ============================================================
function copyColumnData(columnName, cellIndex) {
    const visibleRows = Array.from(document.querySelectorAll('#table-body tr'))
        .filter(r => r.style.display !== 'none');

    if (visibleRows.length === 0) {
        showToast('⚠️ No visible rows to copy.', true);
        return;
    }

    const values = visibleRows.map(row => {
        const cell = row.cells[cellIndex - 1]; // 1-indexed to 0-indexed
        return cell ? cell.textContent.trim() : '';
    }).filter(val => val.length > 0 && val !== 'N/A');

    if (values.length === 0) {
        showToast(`⚠️ No ${columnName} data found to copy.`, true);
        return;
    }

    const copyText = values.join('\n');
    navigator.clipboard.writeText(copyText).then(() => {
        showToast(`📋 Copied ${values.length} ${columnName} entries to clipboard!`, false);
    }).catch(err => {
        console.error('Column copy failed:', err);
        showToast('❌ Failed to copy to clipboard.', true);
    });
}

// ============================================================
// PAGINATION ("LOAD MORE") LOGIC
// ============================================================
function loadNextBatch() {
    const btn = document.getElementById('btn-load-more');
    const errBox = document.getElementById('load-more-error');
    if (!btn || btn.disabled) return;

    btn.disabled = true;
    const origText = btn.innerHTML;
    btn.innerHTML = `⏳ Loading...`;
    if (errBox) errBox.style.display = 'none';

    const url = `/api/search?search_id=${encodeURIComponent(state.searchId || '')}&jd=${encodeURIComponent(state.jobQuery)}&mailbox=${encodeURIComponent(state.mailbox)}&offset=${state.offset}&limit=${state.limit}`;

    fetch(url)
        .then(res => res.json())
        .then(data => {
            btn.disabled = false;
            btn.innerHTML = origText;

            if (data && data.candidates && data.candidates.length > 0) {
                appendRowsToTable(data.candidates, state.offset);
                state.offset += data.candidates.length;
                state.total = data.total || state.total;
                updatePaginationUI();
                applyTableFilters();
            } else if (data && data.candidates && data.candidates.length === 0) {
                state.offset = state.total;
                updatePaginationUI();
            } else {
                showLoadMoreError();
            }
        })
        .catch(err => {
            console.error('Error loading more candidates:', err);
            btn.disabled = false;
            btn.innerHTML = origText;
            showLoadMoreError();
        });
}

function showLoadMoreError() {
    const errBox = document.getElementById('load-more-error');
    if (errBox) {
        errBox.style.display = 'block';
    }
}

function updatePaginationUI() {
    const container = document.getElementById('pagination-bar');
    const counterText = document.getElementById('pagination-counter');
    const btn = document.getElementById('btn-load-more');
    const finishedText = document.getElementById('pagination-finished');

    if (!container) return;

    const visibleCount = Math.min(state.offset, state.total);

    if (state.total === 0) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';

    if (counterText) {
        counterText.textContent = `Showing ${visibleCount} of ${state.total} matches`;
    }

    if (visibleCount >= state.total) {
        if (btn) btn.style.display = 'none';
        if (finishedText) {
            finishedText.style.display = 'inline';
            finishedText.textContent = `All ${state.total} matches loaded.`;
        }
    } else {
        if (btn) {
            btn.style.display = 'inline-flex';
            btn.textContent = `Load Next ${state.limit} →`;
        }
        if (finishedText) finishedText.style.display = 'none';
    }
}

function appendRowsToTable(candidates, startOffset) {
    const tbody = document.getElementById('table-body');
    if (!tbody) return;

    candidates.forEach((row, idx) => {
        const rankNum = startOffset + idx + 1;
        const status = row.Status || 'new';
        const tr = document.createElement('tr');
        tr.setAttribute('id', `row-${rankNum}`);
        tr.setAttribute('data-status', status);
        tr.setAttribute('data-email', row.Email || '');

        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="trainer-checkbox" data-email="${escapeHtml(row.Email || '')}" data-name="${escapeHtml(row.Name || '')}" data-phone="${escapeHtml(row.Phone || '')}" onchange="onTrainerSelectChange()" style="cursor: pointer; transform: scale(1.15);">
            </td>
            <td style="text-align: center;">
                <span class="tag-rank">#${rankNum}</span>
            </td>
            <td style="font-weight: 600;">${escapeHtml(row.Name || 'N/A')}</td>
            <td style="font-size: 0.88rem; color: #334155;">${escapeHtml(row.Email || 'N/A')}</td>
            <td style="font-size: 0.88rem; color: #334155;">${escapeHtml(row.Phone || 'N/A')}</td>
            <td style="text-align: center; white-space: nowrap;">${escapeHtml(row.Experience || 'N/A')}</td>
            <td style="font-size: 0.85rem; line-height: 1.3; color: #475569; word-break: break-word;">${escapeHtml(row['Skill Set'] || 'N/A')}</td>
            <td class="status-cell" style="text-align: center;">
                ${renderStatusBadge(status, row.Email, row.Name)}
            </td>
            <td style="text-align: center;">
                <button type="button" class="btn-action-small btn-copy-action" onclick="copySingleCandidate(this)" title="Copy Candidate Info & Mark as Used">📋 Copy</button>
            </td>
        `;

        tbody.appendChild(tr);
    });
}

function renderStatusBadge(status, email, name) {
    let badgeClass = 'badge-status-new';
    let label = '🟢 New';

    if (status === 'used') {
        badgeClass = 'badge-status-used';
        label = '🔵 Used';
    } else if (status === 'not_used' || status === 'skipped') {
        badgeClass = 'badge-status-notused';
        label = '🟡 Not Used';
    }

    return `
        <div class="status-dropdown-wrapper" style="position: relative; display: inline-block;">
            <button type="button" class="badge-status ${badgeClass}" onclick="toggleStatusMenu(this, event)" style="cursor: pointer; border: none; font-family: inherit;">
                ${label} ▾
            </button>
            <div class="status-menu" style="display: none; position: absolute; top: 100%; left: 50%; transform: translateX(-50%); background: white; border: 1px solid #cbd5e1; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); z-index: 100; min-width: 110px; padding: 4px 0; text-align: left;">
                <div onclick="changeCandidateStatus(this, '${escapeHtml(email || '')}', '${escapeHtml(name || '')}', 'new')" style="padding: 6px 12px; cursor: pointer; font-size: 0.86rem; font-weight: 600; color: #15803d; transition: background 0.15s;" onmouseover="this.style.background='#f0fdf4'" onmouseout="this.style.background='transparent'">🟢 New</div>
                <div onclick="changeCandidateStatus(this, '${escapeHtml(email || '')}', '${escapeHtml(name || '')}', 'used')" style="padding: 6px 12px; cursor: pointer; font-size: 0.86rem; font-weight: 600; color: #1d4ed8; transition: background 0.15s;" onmouseover="this.style.background='#eff6ff'" onmouseout="this.style.background='transparent'">🔵 Used</div>
                <div onclick="changeCandidateStatus(this, '${escapeHtml(email || '')}', '${escapeHtml(name || '')}', 'not_used')" style="padding: 6px 12px; cursor: pointer; font-size: 0.86rem; font-weight: 600; color: #b45309; transition: background 0.15s;" onmouseover="this.style.background='#fefce8'" onmouseout="this.style.background='transparent'">🟡 Not Used</div>
            </div>
        </div>
    `;
}

// ============================================================
// STATUS DROPDOWN MENU
// ============================================================
function toggleStatusMenu(btn, event) {
    if (event) event.stopPropagation();
    const menu = btn.nextElementSibling;
    document.querySelectorAll('.status-menu').forEach(m => {
        if (m !== menu) m.style.display = 'none';
    });
    if (menu) {
        menu.style.display = (menu.style.display === 'block') ? 'none' : 'block';
    }
}

document.addEventListener('click', function () {
    document.querySelectorAll('.status-menu').forEach(m => m.style.display = 'none');
});

function changeCandidateStatus(menuItem, email, name, newStatus) {
    const row = menuItem.closest('tr');
    const oldStatus = row ? row.getAttribute('data-status') : 'new';

    if (row) {
        row.setAttribute('data-status', newStatus);
        const cell = row.querySelector('.status-cell');
        if (cell) {
            cell.innerHTML = renderStatusBadge(newStatus, email, name);
        }
    }

    applyTableFilters();

    const mailbox = state.mailbox || document.getElementById('account_email')?.value || 'recruiter@ecorptrainings.com';

    fetch('/api/candidate/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mailbox, email, name, status: newStatus })
    }).catch(err => {
        console.error('Error updating status:', err);
        if (row) {
            row.setAttribute('data-status', oldStatus);
            const cell = row.querySelector('.status-cell');
            if (cell) cell.innerHTML = renderStatusBadge(oldStatus, email, name);
            applyTableFilters();
        }
        showToast('⚠️ Failed to save status update. Reverted.', true);
    });
}

// ============================================================
// COPY & AUTO-MARK USED WITH 5-SEC UNDO TOAST
// ============================================================
function copySingleCandidate(btn) {
    const row = btn.closest('tr');
    if (!row) return;

    const cb = row.querySelector('.trainer-checkbox');
    const name = cb ? cb.getAttribute('data-name') : row.cells[2].textContent.trim();
    const email = cb ? cb.getAttribute('data-email') : row.cells[3].textContent.trim();
    const phone = cb ? cb.getAttribute('data-phone') : row.cells[4].textContent.trim();

    const formattedText = `${name} | ${email} | ${phone}`;
    const oldStatus = row.getAttribute('data-status') || 'new';

    // 1. Copy to clipboard
    navigator.clipboard.writeText(formattedText).then(() => {
        // 2. Optimistic UI update to 'used'
        row.setAttribute('data-status', 'used');
        const cell = row.querySelector('.status-cell');
        if (cell) cell.innerHTML = renderStatusBadge('used', email, name);
        applyTableFilters();

        // 3. Save to backend
        const mailbox = state.mailbox || 'recruiter@ecorptrainings.com';
        fetch('/api/candidate/status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mailbox, email, name, status: 'used' })
        });

        // 4. Show 5-second Undo Toast
        showUndoToast(1, [{ email, name, oldStatus }]);
    }).catch(err => {
        console.error('Clipboard copy failed:', err);
        showToast('❌ Clipboard copy failed.', true);
    });
}

function copySelectedCandidates() {
    const checked = Array.from(document.querySelectorAll('.trainer-checkbox:checked'));
    if (checked.length === 0) {
        showToast('⚠️ Please select at least one candidate first.', true);
        return;
    }

    const lines = [];
    const itemsToMark = [];
    const restoreList = [];

    checked.forEach(cb => {
        const row = cb.closest('tr');
        const name = cb.getAttribute('data-name') || '';
        const email = cb.getAttribute('data-email') || '';
        const phone = cb.getAttribute('data-phone') || '';
        const oldStatus = row ? (row.getAttribute('data-status') || 'new') : 'new';

        lines.push(`${name} | ${email} | ${phone}`);
        itemsToMark.push({ email, name });
        restoreList.push({ email, name, oldStatus });

        if (row) {
            row.setAttribute('data-status', 'used');
            const cell = row.querySelector('.status-cell');
            if (cell) cell.innerHTML = renderStatusBadge('used', email, name);
        }
    });

    applyTableFilters();

    const formattedText = lines.join('\n');

    navigator.clipboard.writeText(formattedText).then(() => {
        const mailbox = state.mailbox || 'recruiter@ecorptrainings.com';
        fetch('/api/candidate/bulk_status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mailbox, items: itemsToMark, status: 'used' })
        });

        showUndoToast(checked.length, restoreList);
    }).catch(err => {
        console.error('Bulk copy failed:', err);
        showToast('❌ Clipboard copy failed.', true);
    });
}

// ============================================================
// TOAST & UNDO NOTIFICATION
// ============================================================
function showUndoToast(count, restoreList) {
    state.lastCopiedItems = restoreList;

    let toast = document.getElementById('undo-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'undo-toast';
        toast.style.cssText = `
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: #0f172a;
            color: #ffffff;
            padding: 14px 22px;
            border-radius: 10px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.3);
            font-size: 0.92rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 16px;
            z-index: 10000;
            animation: slideInToast 0.25s ease-out;
        `;
        document.body.appendChild(toast);
    }

    if (state.undoTimeout) clearTimeout(state.undoTimeout);

    toast.innerHTML = `
        <span>✅ Copied ${count} candidate${count > 1 ? 's' : ''} (marked as Used).</span>
        <button type="button" onclick="undoLastCopyStatus()" style="background: #2563eb; color: white; border: none; padding: 6px 14px; border-radius: 6px; font-weight: 700; cursor: pointer; font-size: 0.86rem;">[Undo]</button>
    `;
    toast.style.display = 'flex';

    state.undoTimeout = setTimeout(() => {
        if (toast) toast.style.display = 'none';
    }, 5000);
}

function undoLastCopyStatus() {
    const toast = document.getElementById('undo-toast');
    if (toast) toast.style.display = 'none';
    if (state.undoTimeout) clearTimeout(state.undoTimeout);

    if (!state.lastCopiedItems || state.lastCopiedItems.length === 0) return;

    const mailbox = state.mailbox || 'recruiter@ecorptrainings.com';

    state.lastCopiedItems.forEach(item => {
        const tr = document.querySelector(`tr[data-email="${CSS.escape(item.email)}"]`) ||
                   Array.from(document.querySelectorAll('#table-body tr')).find(r => r.cells[3] && r.cells[3].textContent.trim().toLowerCase() === item.email.toLowerCase());

        if (tr) {
            tr.setAttribute('data-status', item.oldStatus);
            const cell = tr.querySelector('.status-cell');
            if (cell) cell.innerHTML = renderStatusBadge(item.oldStatus, item.email, item.name);
        }

        fetch('/api/candidate/status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mailbox, email: item.email, name: item.name, status: item.oldStatus })
        });
    });

    applyTableFilters();
    showToast(`🔄 Reverted status for ${state.lastCopiedItems.length} candidate(s).`, false);
    state.lastCopiedItems = [];
}

function showToast(msg, isError = false) {
    let toast = document.getElementById('simple-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'simple-toast';
        toast.style.cssText = `
            position: fixed;
            bottom: 24px;
            right: 24px;
            padding: 12px 20px;
            border-radius: 8px;
            font-size: 0.9rem;
            font-weight: 600;
            z-index: 10000;
        `;
        document.body.appendChild(toast);
    }
    toast.style.background = isError ? '#991b1b' : '#15803d';
    toast.style.color = '#ffffff';
    toast.textContent = msg;
    toast.style.display = 'block';

    setTimeout(() => {
        if (toast) toast.style.display = 'none';
    }, 3500);
}

// ============================================================
// TOOLBAR SELECTION & FILTERS
// ============================================================
function toggleSelectAll(masterCb) {
    const visibleCheckboxes = Array.from(document.querySelectorAll('#table-body tr'))
        .filter(r => r.style.display !== 'none')
        .map(r => r.querySelector('.trainer-checkbox'))
        .filter(cb => cb !== null);

    visibleCheckboxes.forEach(cb => cb.checked = masterCb.checked);
    onTrainerSelectChange();
}

let currentTab = 'all';

function switchTrainerTab(tab) {
    currentTab = tab;
    const tabAll = document.getElementById('tab-all-trainers');
    const tabSel = document.getElementById('tab-selected-trainers');

    if (tab === 'all') {
        if (tabAll) { tabAll.style.background = '#2563eb'; tabAll.style.color = '#ffffff'; }
        if (tabSel) { tabSel.style.background = 'transparent'; tabSel.style.color = '#475569'; }
    } else {
        if (tabSel) { tabSel.style.background = '#2563eb'; tabSel.style.color = '#ffffff'; }
        if (tabAll) { tabAll.style.background = 'transparent'; tabAll.style.color = '#475569'; }
    }

    applyTableFilters();
}

function onTrainerSelectChange() {
    const checked = document.querySelectorAll('.trainer-checkbox:checked');
    const badge = document.getElementById('selected-count-badge');
    const tabBadge = document.getElementById('tab-selected-count');
    const copyBtn = document.getElementById('btn-copy-selected');

    if (badge) badge.textContent = checked.length;
    if (tabBadge) tabBadge.textContent = checked.length;
    if (copyBtn) copyBtn.textContent = `📋 Copy Selected (${checked.length})`;
}

function applyTableFilters() {
    const statusFilter = document.getElementById('status-filter-select')?.value || 'all';
    const hideUsed = document.getElementById('chk-hide-used')?.checked ?? true;
    const textFilter = document.getElementById('filter-box')?.value.toLowerCase().trim() || '';
    const minScore = parseInt(document.getElementById('score-slider')?.value || '0', 10);

    const rows = document.querySelectorAll('#table-body tr');
    let visibleCount = 0;

    rows.forEach(row => {
        const status = row.getAttribute('data-status') || 'new';
        const rowText = row.textContent.toLowerCase();
        const cb = row.querySelector('.trainer-checkbox');
        const isChecked = cb && cb.checked;

        // Tab filter
        let showByTab = true;
        if (currentTab === 'selected' && !isChecked) {
            showByTab = false;
        }

        // Score filter
        let showByScore = true;
        if (minScore > 0) {
            const scoreText = row.cells[10] ? row.cells[10].textContent.replace(/[^\d]/g, '') : '';
            const scoreVal = parseInt(scoreText || '0', 10);
            if (scoreVal < minScore) {
                showByScore = false;
            }
        }

        // Status filter
        let showByStatus = true;
        if (hideUsed && status === 'used') {
            showByStatus = false;
        } else if (statusFilter === 'new' && status !== 'new') {
            showByStatus = false;
        } else if (statusFilter === 'used' && status !== 'used') {
            showByStatus = false;
        } else if (statusFilter === 'not_used' && (status !== 'not_used' && status !== 'skipped')) {
            showByStatus = false;
        }

        let showByText = !textFilter || rowText.includes(textFilter);

        if (showByTab && showByScore && showByStatus && showByText) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });

    const visibleBadge = document.getElementById('visible-count');
    if (visibleBadge) visibleBadge.textContent = visibleCount;

    const checked = document.querySelectorAll('.trainer-checkbox:checked');
    const tabBadge = document.getElementById('tab-selected-count');
    if (tabBadge) tabBadge.textContent = checked.length;
}

function downloadCSV() {
    const visibleRows = Array.from(document.querySelectorAll('#table-body tr'))
        .filter(r => r.style.display !== 'none');

    if (visibleRows.length === 0) {
        showToast('⚠️ No visible candidate rows to export.', true);
        return;
    }

    const headers = ["Rank", "Status", "Name", "Gender", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason"];
    const csvLines = [headers.join(",")];

    visibleRows.forEach(row => {
        const rowData = [
            `"${(row.cells[1]?.textContent.trim() || '').replace(/"/g, '""')}"`,
            `"${(row.getAttribute('data-status') || '').replace(/"/g, '""')}"`,
            `"${(row.cells[3]?.textContent.trim() || '').replace(/"/g, '""')}"`,
            `"${(row.cells[4]?.textContent.trim() || '').replace(/"/g, '""')}"`,
            `"${(row.cells[5]?.textContent.trim() || '').replace(/"/g, '""')}"`,
            `"${(row.cells[6]?.textContent.trim() || '').replace(/"/g, '""')}"`,
            `"${(row.cells[7]?.textContent.trim() || '').replace(/"/g, '""')}"`,
            `"${(row.cells[8]?.textContent.trim() || '').replace(/"/g, '""')}"`,
            `"${(row.cells[9]?.textContent.trim() || '').replace(/"/g, '""')}"`,
            `"${(row.cells[10]?.textContent.trim() || '').replace(/"/g, '""')}"`,
            `"${(row.cells[11]?.textContent.trim() || '').replace(/"/g, '""')}"`
        ];
        csvLines.push(rowData.join(","));
    });

    const csvBlob = new Blob([csvLines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(csvBlob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `Shortlisted_Candidates_${new Date().toISOString().slice(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast(`📥 Exported ${visibleRows.length} candidates to CSV!`, false);
}
