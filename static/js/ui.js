/**
 * ResuMatch UI Controller (Toasts, Side Panels, Theme Toggle)
 */

// ========== SEARCH PROGRESS POLLING ==========
let pollingInterval = null;

function startPolling(searchId) {
    if (!searchId) {
        console.error("[poll] startPolling called without searchId");
        return;
    }
    
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
    
    console.log("[poll] starting for", searchId);
    let pollCount = 0;
    
    pollingInterval = setInterval(async () => {
        pollCount++;
        if (pollCount > 300) {
            clearInterval(pollingInterval);
            pollingInterval = null;
            if (typeof stopLoadingSpinner === "function") stopLoadingSpinner();
            alert("Search timed out after 10 minutes");
            return;
        }
        
        try {
            const res = await fetch(`/api/search/progress/${searchId}`);
            const data = await res.json();
            
            console.log(`[poll] #${pollCount} status=${data.status} progress=${data.progress} candidates=${(data.candidates||[]).length}`);
            
            if (typeof updateProgressBar === "function") {
                updateProgressBar(data.progress || 0, data.message || "");
            }
            
            if (data.status === "done") {
                clearInterval(pollingInterval);
                pollingInterval = null;
                if (typeof stopLoadingSpinner === "function") stopLoadingSpinner();
                
                const candidates = data.candidates || [];
                console.log("[poll] DONE with", candidates.length, "candidates");
                
                if (typeof renderCandidates === "function") {
                    renderCandidates(candidates);
                } else if (typeof window.renderResults === "function") {
                    window.renderResults(candidates);
                } else {
                    console.warn("[poll] no render function found, showing alert");
                    alert("Search complete: " + candidates.length + " candidates");
                    console.log(candidates);
                }
                return;
            }
            
            if (data.status === "error") {
                clearInterval(pollingInterval);
                pollingInterval = null;
                if (typeof stopLoadingSpinner === "function") stopLoadingSpinner();
                alert("Search failed: " + (data.error || "unknown error"));
                return;
            }
        } catch (err) {
            console.error("[poll] fetch error:", err);
        }
    }, 2000);
}
window.startPolling = startPolling;
// ========== END POLLING ==========

document.addEventListener('DOMContentLoaded', function() {
    // 1. Theme toggle persistence
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);

    const themeBtn = document.getElementById('theme-toggle-btn');
    if (themeBtn) {
        themeBtn.addEventListener('click', function() {
            const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
            const newTheme = (currentTheme === 'light') ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            updateThemeIcon(newTheme);
        });
    }

    // 2. History Side Panel trigger
    const historyBtn = document.getElementById('btn-history-panel');
    const panel = document.getElementById('history-side-panel');
    const overlay = document.getElementById('history-panel-overlay');
    const closeBtn = document.getElementById('btn-close-history');

    if (historyBtn && panel && overlay) {
        historyBtn.addEventListener('click', function(e) {
            e.preventDefault();
            if (typeof closeCopiedPanel === 'function') closeCopiedPanel();
            panel.classList.add('active');
            overlay.classList.add('active');
            fetchRecentHistoryPanel();
        });
    }

    if (closeBtn && panel && overlay) {
        closeBtn.addEventListener('click', closeHistoryPanel);
        overlay.addEventListener('click', closeHistoryPanel);
    }
});

function updateThemeIcon(theme) {
    const iconElem = document.getElementById('theme-icon');
    if (iconElem) {
        const icName = (theme === 'dark') ? 'sun' : 'moon';
        iconElem.innerHTML = window.icon ? window.icon(icName, 16) : '';
    }
}

function closeHistoryPanel() {
    const panel = document.getElementById('history-side-panel');
    const overlay = document.getElementById('history-panel-overlay');
    if (panel) panel.classList.remove('active');
    if (overlay) overlay.classList.remove('active');
}

function fetchRecentHistoryPanel() {
    const content = document.getElementById('history-panel-content');
    if (!content) return;
    const icLoader = window.icon ? window.icon('loader', 16, 'animate-spin') : '';
    content.innerHTML = `<div style="text-align:center; padding: 20px; color: var(--text-muted); display:flex; align-items:center; justify-content:center; gap:8px;">${icLoader} Loading recent history...</div>`;

    fetch('/api/history?days=30')
        .then(res => res.json())
        .then(data => {
            if (data && data.history && data.history.length > 0) {
                let html = '<div style="display:flex; flex-direction:column; gap: 12px;">';
                data.history.forEach(item => {
                    const dateStr = item.searched_at || item.created_at;
                    const formattedDate = dateStr ? new Date(dateStr).toLocaleString('en-GB') : 'Recent';
                    const icCal = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`;
                    const icMail = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>`;
                    const icUsers = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>`;
                    const icDetails = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>`;
                    const icRerun = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>`;
                    
                    html += `
                        <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px 16px; box-shadow: 0 2px 6px rgba(0,0,0,0.02);">
                            <div style="font-size: 0.82rem; color: #94a3b8; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                                ${icCal} ${formattedDate}
                            </div>
                            <div style="font-size: 0.88rem; color: #475569; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
                                ${icMail} ${escapeHtmlUI(item.mailbox_account || '')}
                            </div>
                            <div style="font-size: 0.95rem; font-weight: 700; color: #4f46e5; margin-bottom: 12px;">
                                "${escapeHtmlUI(item.job_description || '')}"
                            </div>
                            <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                                <span style="font-size: 0.86rem; color: #64748b; font-weight: 600; display: inline-flex; align-items: center; gap: 6px;">
                                    ${icUsers} ${item.results_count || 0} candidates
                                </span>
                                <div style="display: flex; gap: 8px; flex-shrink: 0; align-items: center;">
                                    <button type="button" onclick="viewHistoryDetailsModal('${escapeHtmlUI(item.id)}')" style="background: #ffffff; border: 1.5px solid #cbd5e1; color: #1e293b; padding: 6px 14px; border-radius: 8px; font-weight: 600; font-size: 0.82rem; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; transition: background 0.15s;">
                                        ${icDetails} Details
                                    </button>
                                    <button type="button" onclick="rerunHistorySearch('${escapeHtmlUI(item.job_description || '')}', '${escapeHtmlUI(item.mailbox_account || '')}')" style="background: #4f46e5; border: none; color: #ffffff; padding: 6px 14px; border-radius: 8px; font-weight: 600; font-size: 0.82rem; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; transition: background 0.15s;">
                                        ${icRerun} Re-run
                                    </button>
                                </div>
                            </div>
                        </div>
                    `;
                });
                html += '</div>';
                content.innerHTML = html;
            } else {
                content.innerHTML = '<div style="text-align:center; padding: 30px; color: var(--text-muted);">No search history records found.</div>';
            }
        })
        .catch(err => {
            console.error('Error fetching history:', err);
            content.innerHTML = '<div style="text-align:center; padding: 20px; color: var(--danger);">Failed to load history.</div>';
        });
}

function viewHistoryDetailsModal(searchId) {
    let modal = document.getElementById('history-details-modal');
    let overlay = document.getElementById('history-details-modal-overlay');

    if (!modal) {
        overlay = document.createElement('div');
        overlay.id = 'history-details-modal-overlay';
        overlay.style.cssText = 'position: fixed; inset: 0; background: rgba(15, 23, 42, 0.5); backdrop-filter: blur(4px); z-index: 10005; display: flex; align-items: center; justify-content: center; padding: 20px;';

        modal = document.createElement('div');
        modal.id = 'history-details-modal';
        modal.style.cssText = 'background: var(--bg-card); color: var(--text-primary); width: 100%; max-width: 520px; max-height: 80vh; border-radius: var(--radius-lg); box-shadow: var(--shadow-md); border: 1px solid var(--border); overflow-y: auto; padding: 20px; z-index: 10006; animation: slideInToast 0.2s ease-out;';
        
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeHistoryDetailsModal();
        });
    } else {
        overlay.style.display = 'flex';
    }

    const icLoader = window.icon ? window.icon('loader', 16, 'animate-spin') : '';
    modal.innerHTML = `<div style="text-align:center; padding: 20px; color: var(--text-secondary); display:flex; align-items:center; justify-content:center; gap:8px;">${icLoader} Loading details...</div>`;

    fetch('/api/history/' + searchId)
        .then(res => res.json())
        .then(res => {
            if (res.success && res.data) {
                const data = res.data;
                let candHtml = '';
                if (data.candidates_seen && data.candidates_seen.length > 0) {
                    candHtml = '<ul style="padding-left: 20px; line-height: 1.5; max-height: 220px; overflow-y: auto; font-size: 13px;">';
                    data.candidates_seen.forEach(c => {
                        let cName = 'Candidate';
                        let cEmail = 'N/A';
                        if (typeof c === 'string') {
                            cEmail = c;
                            cName = c.includes('@') ? c.split('@')[0] : c;
                        } else if (c && typeof c === 'object') {
                            cName = c.Name || c.name || (c.Email || c.email ? (c.Email || c.email).split('@')[0] : 'Candidate');
                            cEmail = c.Email || c.email || 'N/A';
                        }
                        candHtml += `<li><strong style="color: var(--text-primary);">${escapeHtmlUI(cName)}</strong> <span style="color: var(--text-secondary);">(${escapeHtmlUI(cEmail)})</span></li>`;
                    });
                    candHtml += '</ul>';
                } else {
                    candHtml = '<p style="color: var(--text-muted); font-size: 12px;">No candidate list cached for this search.</p>';
                }

                const icClose = window.icon ? window.icon('x', 16) : '✕';
                modal.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 14px;">
                        <h3 style="margin: 0; font-size: 15px; font-weight: 600; color: var(--text-primary);">Search Details</h3>
                        <button type="button" onclick="closeHistoryDetailsModal()" class="btn-ghost-icon">${icClose}</button>
                    </div>
                    <div style="font-size: 13px; line-height: 1.5; color: var(--text-primary);">
                        <p style="margin: 4px 0;"><strong>Mailbox:</strong> <span style="color: var(--accent);">${escapeHtmlUI(data.mailbox_account || '')}</span></p>
                        <p style="margin: 4px 0;"><strong>Date & Time:</strong> ${escapeHtmlUI(data.searched_at || '')}</p>
                        <p style="margin: 4px 0;"><strong>Job Query:</strong> "${escapeHtmlUI(data.job_description || '')}"</p>
                        <p style="margin: 4px 0;"><strong>Batch Limit:</strong> ${data.batch_size} &nbsp;·&nbsp; <strong>Found:</strong> ${data.results_count}</p>
                        <h4 style="margin-top: 14px; margin-bottom: 6px; color: var(--text-primary); font-size: 13px;">Candidates Returned (${data.results_count}):</h4>
                        ${candHtml}
                    </div>
                    <div style="text-align: right; margin-top: 16px; border-top: 1px solid var(--border); padding-top: 10px;">
                        <button type="button" onclick="closeHistoryDetailsModal()" class="btn-primary-lg" style="height: 32px; padding: 0 14px; font-size: 13px;">Close</button>
                    </div>
                `;
            } else {
                modal.innerHTML = '<div style="color: var(--danger); padding: 12px;">Failed to load search details.</div>';
            }
        })
        .catch(err => {
            console.error('Error fetching search details:', err);
            modal.innerHTML = '<div style="color: var(--danger); padding: 12px;">Failed to load search details.</div>';
        });
}

function closeHistoryDetailsModal() {
    const overlay = document.getElementById('history-details-modal-overlay');
    if (overlay) overlay.style.display = 'none';
}

function rerunHistorySearch(query, mailbox) {
    closeHistoryPanel();
    const queryInput = document.getElementById('job_query');
    const acctSelect = document.getElementById('account_email');
    if (queryInput) queryInput.value = query;
    if (acctSelect && mailbox) acctSelect.value = mailbox;
    const form = document.getElementById('search-form');
    if (form) form.submit();
}

function escapeHtmlUI(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
