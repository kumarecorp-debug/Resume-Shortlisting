/**
 * Copy Controller & "Skip Already-Copied?" Prompt Interceptor
 */

document.addEventListener('DOMContentLoaded', function () {
    const searchForm = document.getElementById('search-form');
    if (!searchForm) return;

    searchForm.addEventListener('submit', function (e) {
        if (window._skipCopiedHandled) {
            window._skipCopiedHandled = false;
            return; // Allow form submission
        }

        const mailbox = document.getElementById('account_email')?.value || '';
        const jd = document.getElementById('job_query')?.value || '';
        const sessionKey = `copy_pref_${mailbox.toLowerCase().strip ? mailbox.toLowerCase().strip() : mailbox.toLowerCase()}_${jd.toLowerCase().trim()}`;
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
    const currentMail = document.getElementById('account_email')?.value || '';
    const currentJd = document.getElementById('job_query')?.value || '';
    if (currentMail && currentJd) {
        const sessionKey = `copy_pref_${currentMail.toLowerCase()}_${currentJd.toLowerCase().trim()}`;
        if (sessionStorage.getItem(sessionKey)) {
            const link = document.getElementById('link-change-copy-pref');
            if (link) link.style.display = 'inline-block';
            applyCopiedPreference(sessionStorage.getItem(sessionKey));
        }
    }
});

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
