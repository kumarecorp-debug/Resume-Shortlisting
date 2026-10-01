// Global search context
window.__currentMailbox = document.getElementById('account_email')?.value || '';
window.__currentJD = document.getElementById('job_query')?.value || '';

document.addEventListener('DOMContentLoaded', function () {
    const searchForm = document.getElementById('search-form');
    const accountSelect = document.getElementById('account_email');
    const jobQueryTextarea = document.getElementById('job_query');

    // Update global search context
    function updateGlobals() {
        window.__currentMailbox = accountSelect?.value || '';
        window.__currentJD = jobQueryTextarea?.value || '';
    }
    updateGlobals();

    if (accountSelect) accountSelect.addEventListener('change', updateGlobals);
    if (jobQueryTextarea) jobQueryTextarea.addEventListener('input', updateGlobals);

    if (!searchForm) return;

    searchForm.addEventListener('submit', function (e) {
        updateGlobals();

        if (window._skipCopiedHandled) {
            window._skipCopiedHandled = false;
            return; // Allow form submission
        }

        const mailbox = window.__currentMailbox;
        const jd = window.__currentJD;
        const keyMailbox = (mailbox || '').toLowerCase().trim();
        const keyJd = (jd || '').toLowerCase().trim();
        const sessionKey = `copy_pref_${keyMailbox}_${keyJd}`;
        const savedPref = sessionStorage.getItem(sessionKey);

        if (savedPref) {
            applyCopiedPreference(savedPref);
            return; // Continue form submission
        }

        e.preventDefault();

        fetch(`/api/copied-history/check?mailbox=${encodeURIComponent(mailbox)}&jd=${encodeURIComponent(jd)}`)
            .then(res => res.json())
            .then(data => {
                if (data.has_copies) {
                    showSkipCopiedModal(mailbox, jd, data, sessionKey, searchForm);
                } else {
                    window._skipCopiedHandled = true;
                    searchForm.submit();
                }
            })
            .catch(err => {
                console.error('Error checking copied history:', err);
                window._skipCopiedHandled = true;
                searchForm.submit();
            });
    });

    // Check if session preference exists for current search to show Change Preference link
    const currentMail = window.__currentMailbox;
    const currentJd = window.__currentJD;
    if (currentMail && currentJd) {
        const sessionKey = `copy_pref_${currentMail.toLowerCase().trim()}_${currentJd.toLowerCase().trim()}`;
        if (sessionStorage.getItem(sessionKey)) {
            const link = document.getElementById('link-change-copy-pref');
            if (link) link.style.display = 'inline-block';
            applyCopiedPreference(sessionStorage.getItem(sessionKey));
        }
    }
});

// Helper POST functions for copying
async function saveCandidateToCopiedHistory(candidate) {
    const mailbox = window.__currentMailbox || document.getElementById('account_email')?.value || '';
    const jd = window.__currentJD || document.getElementById('job_query')?.value || '';

    try {
        const res = await fetch('/api/copied-history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mailbox_account: mailbox,
                candidate_email: candidate.email || candidate.candidate_email || candidate.Email || '',
                candidate_name: candidate.name || candidate.candidate_name || candidate.Name || '',
                candidate_phone: candidate.phone || candidate.candidate_phone || candidate.Phone || '',
                job_description: jd
            })
        });
        const data = await res.json();
        console.log('[copied-history POST]', data);
        if (data.success) {
            if (typeof refreshCopiedHistoryPanel === 'function') refreshCopiedHistoryPanel();
            if (typeof updateCopiedHistoryCount === 'function') updateCopiedHistoryCount();
            if (typeof updateCopiedHistoryBadge === 'function') updateCopiedHistoryBadge();
        }
        return data;
    } catch (err) {
        console.error('[copied-history POST] failed:', err);
        return { success: false, error: err };
    }
}

async function saveBulkCandidatesToCopiedHistory(candidates) {
    const mailbox = window.__currentMailbox || document.getElementById('account_email')?.value || '';
    const jd = window.__currentJD || document.getElementById('job_query')?.value || '';

    try {
        const res = await fetch('/api/copied-history/bulk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mailbox_account: mailbox,
                job_description: jd,
                candidates: (candidates || []).map(c => ({
                    email: c.email || c.candidate_email || c.Email || '',
                    name: c.name || c.candidate_name || c.Name || '',
                    phone: c.phone || c.candidate_phone || c.Phone || ''
                }))
            })
        });
        const data = await res.json();
        console.log('[copied-history BULK]', data);
        if (data.success) {
            if (typeof refreshCopiedHistoryPanel === 'function') refreshCopiedHistoryPanel();
            if (typeof updateCopiedHistoryCount === 'function') updateCopiedHistoryCount();
            if (typeof updateCopiedHistoryBadge === 'function') updateCopiedHistoryBadge();
        }
        return data;
    } catch (err) {
        console.error('[copied-history BULK] failed:', err);
        return { success: false, error: err };
    }
}

function showSkipCopiedModal(mailbox, jd, data, sessionKey, form) {
    const overlay = document.getElementById('skip-copied-modal-overlay');
    const mbElem = document.getElementById('modal-skip-mailbox');
    const jdElem = document.getElementById('modal-skip-jd');
    const countElem = document.getElementById('modal-skip-count');
    const listElem = document.getElementById('modal-skip-list');
    const btnSkipText = document.getElementById('btn-skip-count-text');
    const btnShowText = document.getElementById('btn-show-count-text');

    if (!overlay) {
        window._skipCopiedHandled = true;
        form.submit();
        return;
    }

    if (mbElem) mbElem.textContent = mailbox;
    if (jdElem) jdElem.textContent = jd;
    if (countElem) countElem.textContent = data.copied_count || 0;
    if (btnSkipText) btnSkipText.textContent = data.copied_count || 0;
    if (btnShowText) btnShowText.textContent = data.copied_count || 0;

    if (listElem) {
        let itemsHtml = '<ul style="margin:0; padding-left: 18px; line-height: 1.5;">';
        const names = data.candidate_names || [];
        names.slice(0, 5).forEach(n => {
            itemsHtml += `<li><strong>${escapeHtmlUI(n)}</strong></li>`;
        });
        if (names.length > 5) {
            itemsHtml += `<li>... (${names.length - 5} more)</li>`;
        }
        itemsHtml += '</ul>';
        listElem.innerHTML = itemsHtml;
    }

    overlay.style.display = 'flex';

    const btnSkip = document.getElementById('btn-skip-choice-skip');
    const btnShow = document.getElementById('btn-skip-choice-show');
    const btnCancel = document.getElementById('btn-skip-choice-cancel');

    const handleChoice = (choice) => {
        sessionStorage.setItem(sessionKey, choice);
        window._copiedHistoryData = data;
        applyCopiedPreference(choice);
        overlay.style.display = 'none';

        const link = document.getElementById('link-change-copy-pref');
        if (link) link.style.display = 'inline-block';

        window._skipCopiedHandled = true;
        form.submit();
    };

    if (btnSkip) btnSkip.onclick = () => handleChoice('skip');
    if (btnShow) btnShow.onclick = () => handleChoice('show');
    if (btnCancel) btnCancel.onclick = () => { overlay.style.display = 'none'; };
}

function applyCopiedPreference(choice) {
    window._activeCopyChoice = choice;
    const data = window._copiedHistoryData;

    if (choice === 'skip' && data && data.candidate_emails) {
        // Hide copied candidates from table
        const emails = data.candidate_emails.map(e => e.toLowerCase());
        const rows = document.querySelectorAll('#table-body tr');
        let hiddenCount = 0;

        rows.forEach(row => {
            const rowEmail = (row.querySelector('.trainer-checkbox')?.getAttribute('data-email') || row.cells[3]?.textContent.trim()).toLowerCase();
            if (emails.includes(rowEmail)) {
                row.style.display = 'none';
                row.setAttribute('data-hidden-copied', 'true');
                hiddenCount++;
            }
        });

        const titleSpan = document.querySelector('#candidates-count-title span');
        if (titleSpan) {
            let cur = titleSpan.innerHTML;
            if (!cur.includes('hidden — already copied')) {
                titleSpan.innerHTML += ` &nbsp;·&nbsp; <span style="color: var(--text-muted);">(${hiddenCount} hidden — already copied)</span>`;
            }
        }
    } else if (choice === 'show' && data && data.candidate_emails) {
        // Add 📋 Copied badge to candidates
        const emails = data.candidate_emails.map(e => e.toLowerCase());
        const rows = document.querySelectorAll('#table-body tr');

        rows.forEach(row => {
            const rowEmail = (row.querySelector('.trainer-checkbox')?.getAttribute('data-email') || row.cells[3]?.textContent.trim()).toLowerCase();
            if (emails.includes(rowEmail)) {
                const statusCell = row.querySelector('.status-cell');
                if (statusCell && !statusCell.querySelector('.tag-copied-icon')) {
                    const badge = document.createElement('span');
                    badge.className = 'tag-copied-icon';
                    badge.innerHTML = ' 📋';
                    badge.title = 'Candidate previously copied';
                    statusCell.appendChild(badge);
                }
            }
        });
    }
}

function reopenCopyPrefModal(e) {
    if (e) e.preventDefault();
    const mailbox = document.getElementById('account_email')?.value || '';
    const jd = document.getElementById('job_query')?.value || '';
    const sessionKey = `copy_pref_${mailbox.toLowerCase()}_${jd.toLowerCase().trim()}`;
    sessionStorage.removeItem(sessionKey);

    fetch(`/api/copied-history/check?mailbox=${encodeURIComponent(mailbox)}&jd=${encodeURIComponent(jd)}`)
        .then(res => res.json())
        .then(data => {
            showSkipCopiedModal(mailbox, jd, data, sessionKey, document.getElementById('search-form'));
        });
}

// ============================================================
// SELECTED TRAINERS & DIRECT ROW COPY HANDLERS
// ============================================================

window.__selectedTrainers = window.__selectedTrainers || [];

function getSelectedSessionKey() {
    const mb = (window.__currentMailbox || document.getElementById('account_email')?.value || '').toLowerCase().trim();
    const jd = (window.__currentJD || document.getElementById('job_query')?.value || '').toLowerCase().trim();
    return `selected_trainers_${mb}_${jd}`;
}

function saveSelectedTrainersToSession() {
    try {
        const key = getSelectedSessionKey();
        sessionStorage.setItem(key, JSON.stringify(window.__selectedTrainers || []));
    } catch (e) {
        console.warn('[copy] Failed to save selected trainers to sessionStorage:', e);
    }
}

function loadSelectedTrainersFromSession() {
    try {
        const key = getSelectedSessionKey();
        const saved = sessionStorage.getItem(key);
        if (saved) {
            window.__selectedTrainers = JSON.parse(saved) || [];
        }
    } catch (e) {
        console.warn('[copy] Failed to load selected trainers from sessionStorage:', e);
        window.__selectedTrainers = [];
    }
    updateSelectedTrainersUI();
}

function updateSelectedTrainersUI() {
    const count = (window.__selectedTrainers || []).length;
    const tabBadge = document.getElementById('tab-selected-count');
    if (tabBadge) {
        tabBadge.textContent = count;
        tabBadge.style.fontWeight = count > 0 ? '700' : '600';
    }

    const clearBtn = document.getElementById('btn-clear-selected-tab');
    if (clearBtn) {
        clearBtn.style.display = count > 0 ? 'inline-block' : 'none';
    }

    // Mark rows visually in DOM
    const selectedEmails = new Set((window.__selectedTrainers || []).map(c => (c.email || c.Email || '').toLowerCase().trim()));
    document.querySelectorAll('#table-body tr').forEach(row => {
        const em = (row.getAttribute('data-email') || row.querySelector('.cand-email')?.textContent || '').toLowerCase().trim();
        if (em && selectedEmails.has(em)) {
            row.classList.add('tr-copied-highlight');
            row.setAttribute('data-status', 'used');
            const btn = row.querySelector('.btn-row-copy');
            if (btn) {
                btn.disabled = true;
                btn.style.background = '#dcfce7';
                btn.style.color = '#15803d';
                btn.style.borderColor = '#86efac';
                const iconSpan = btn.querySelector('.copy-icon');
                const textSpan = btn.querySelector('.copy-text');
                if (iconSpan) iconSpan.textContent = '✅';
                if (textSpan) textSpan.textContent = 'Copied';
            }
        }
    });
}

window.clearSelectedTrainers = function() {
    if (!window.__selectedTrainers || window.__selectedTrainers.length === 0) return;
    if (confirm("Are you sure you want to clear the selected trainers list?")) {
        window.__selectedTrainers = [];
        saveSelectedTrainersToSession();
        updateSelectedTrainersUI();
        if (typeof applyTableFilters === 'function') applyTableFilters();
        if (typeof showToast === 'function') showToast("Cleared selected trainers list.", false);
    }
};

window.handleRowCopy = async function(btnElem, name, email, phone) {
    console.log('[copy] clicked for:', email);
    if (!email) {
        console.warn('[copy] missing candidate email');
        return;
    }

    const row = btnElem.closest('tr');
    const iconSpan = btnElem.querySelector('.copy-icon');
    const textSpan = btnElem.querySelector('.copy-text');
    const origIcon = iconSpan ? iconSpan.textContent : '📋';
    const origText = textSpan ? textSpan.textContent : 'Copy';

    // Show loading spinner
    btnElem.disabled = true;
    if (iconSpan) iconSpan.textContent = '⏳';
    if (textSpan) textSpan.textContent = 'Saving...';
    btnElem.style.opacity = '0.75';

    // 1. Copy to clipboard
    const textToCopy = `${name} | ${email} | ${phone}`;
    try {
        await navigator.clipboard.writeText(textToCopy);
    } catch (clipErr) {
        console.warn('[copy] clipboard failed:', clipErr);
    }

    const mailbox = window.__currentMailbox || document.getElementById('account_email')?.value || '';
    const jd = window.__currentJD || document.getElementById('job_query')?.value || '';

    try {
        // 2. POST to /api/copied-history
        const resCopied = await fetch('/api/copied-history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mailbox_account: mailbox,
                candidate_email: email,
                candidate_name: name,
                candidate_phone: phone,
                job_description: jd
            })
        });
        const dataCopied = await resCopied.json();
        console.log('[copy] saved to copied_history:', dataCopied);

        if (!resCopied.ok || (dataCopied && dataCopied.success === false)) {
            throw new Error(dataCopied.error || 'Failed to save to copied history');
        }

        // 3. POST to /api/candidate/status with status='used'
        const resStatus = await fetch('/api/candidate/status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mailbox_account: mailbox,
                candidate_email: email,
                candidate_name: name,
                status: 'used'
            })
        });
        const dataStatus = await resStatus.json();
        console.log('[copy] candidate status updated:', dataStatus);

        // 4. Update UI for the row
        if (row) {
            row.setAttribute('data-status', 'used');
            row.classList.add('tr-copied-highlight');
        }

        // Button success state
        btnElem.disabled = true;
        btnElem.style.opacity = '1';
        btnElem.style.background = '#dcfce7';
        btnElem.style.color = '#15803d';
        btnElem.style.borderColor = '#86efac';
        if (iconSpan) iconSpan.textContent = '✅';
        if (textSpan) textSpan.textContent = 'Copied';

        // 5. Add candidate to window.__selectedTrainers array
        const emLower = email.toLowerCase().trim();
        const exists = window.__selectedTrainers.some(c => (c.email || c.Email || '').toLowerCase().trim() === emLower);
        if (!exists) {
            window.__selectedTrainers.push({
                name: name,
                email: email,
                phone: phone,
                copiedAt: new Date().toISOString()
            });
            saveSelectedTrainersToSession();
        }

        updateSelectedTrainersUI();

        // 6. Show Toast
        if (typeof showToast === 'function') {
            showToast(`📋 Copied ${name || email} (marked as Used)`, false);
        }

        // Trigger updates for side panels if present
        if (typeof refreshCopiedHistoryPanel === 'function') refreshCopiedHistoryPanel();
        if (typeof updateCopiedHistoryCount === 'function') updateCopiedHistoryCount();
        if (typeof updateCopiedHistoryBadge === 'function') updateCopiedHistoryBadge();

    } catch (err) {
        console.error('[copy] Error:', err);
        // Revert UI on failure
        btnElem.disabled = false;
        btnElem.style.opacity = '1';
        if (iconSpan) iconSpan.textContent = '❌';
        if (textSpan) textSpan.textContent = 'Error';
        setTimeout(() => {
            if (iconSpan) iconSpan.textContent = origIcon;
            if (textSpan) textSpan.textContent = origText;
        }, 2500);

        if (typeof showToast === 'function') {
            showToast(`❌ Failed to copy candidate: ${err.message || err}`, true);
        }
    }
};

window.copyCandidate = window.handleRowCopy;

document.addEventListener('DOMContentLoaded', function() {
    loadSelectedTrainersFromSession();
});

console.log('[copy.js] handleRowCopy registered:', typeof window.handleRowCopy);

