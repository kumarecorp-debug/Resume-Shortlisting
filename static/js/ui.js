/**
 * ResuMatch UI Controller (Toasts, Side Panels, Theme Toggle)
 */

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
    const icon = document.getElementById('theme-icon');
    if (icon) {
        icon.textContent = (theme === 'dark') ? '☀️' : '🌙';
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
    content.innerHTML = '<div style="text-align:center; padding: 20px; color: var(--text-muted);">⏳ Loading recent history...</div>';

    fetch('/api/history?days=30')
        .then(res => res.json())
        .then(data => {
            if (data && data.history && data.history.length > 0) {
                let html = '<div style="display:flex; flex-direction:column; gap: 14px;">';
                data.history.forEach(item => {
                    const dateStr = item.searched_at || item.created_at;
                    html += `
                        <div style="background: var(--bg-primary); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 14px;">
                            <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">
                                📅 ${dateStr ? new Date(dateStr).toLocaleString() : 'Recent'}
                            </div>
                            <div style="font-size: 0.85rem; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px;">
                                📬 ${escapeHtmlUI(item.mailbox_account || '')}
                            </div>
                            <div style="font-size: 0.95rem; font-weight: 700; color: var(--accent); margin-bottom: 8px;">
                                "${escapeHtmlUI(item.job_description || '')}"
                            </div>
                            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap: wrap; gap: 8px;">
                                <span style="font-size: 0.82rem; color: var(--text-secondary);">
                                    📊 ${item.results_count || 0} candidates
                                </span>
                                <div style="display:flex; gap: 6px;">
                                    <button type="button" onclick="viewHistoryDetailsModal('${escapeHtmlUI(item.id)}')" style="background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 4px 10px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; cursor: pointer;">
                                        👁️ Details
                                    </button>
                                    <button type="button" onclick="rerunHistorySearch('${escapeHtmlUI(item.job_description || '')}', '${escapeHtmlUI(item.mailbox_account || '')}')" style="background: var(--accent); color: white; border: none; padding: 4px 10px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; cursor: pointer;">
                                        Re-run 🔄
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
        modal.style.cssText = 'background: var(--bg-card); color: var(--text-primary); width: 100%; max-width: 540px; max-height: 80vh; border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); border: 1px solid var(--border); overflow-y: auto; padding: 24px; z-index: 10006; animation: slideInToast 0.2s ease-out;';
        
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeHistoryDetailsModal();
        });
    } else {
        overlay.style.display = 'flex';
    }

    modal.innerHTML = '<div style="text-align:center; padding: 20px; color: var(--text-secondary);">⏳ Loading details...</div>';

    fetch('/api/history/' + searchId)
        .then(res => res.json())
        .then(res => {
            if (res.success && res.data) {
                const data = res.data;
                let candHtml = '';
                if (data.candidates_seen && data.candidates_seen.length > 0) {
                    candHtml = '<ul style="padding-left: 20px; line-height: 1.6; max-height: 240px; overflow-y: auto; font-size: 0.9rem;">';
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
                    candHtml = '<p style="color: var(--text-muted); font-size: 0.88rem;">No candidate list cached for this search.</p>';
                }

                modal.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 16px;">
                        <h3 style="margin: 0; font-size: 1.15rem; font-weight: 700; color: var(--text-primary);">Search Details</h3>
                        <button type="button" onclick="closeHistoryDetailsModal()" style="background: none; border: none; font-size: 1.25rem; cursor: pointer; color: var(--text-secondary);">✕</button>
                    </div>
                    <div style="font-size: 0.9rem; line-height: 1.5; color: var(--text-primary);">
                        <p style="margin: 4px 0;"><strong>Mailbox:</strong> <span style="color: var(--accent);">${escapeHtmlUI(data.mailbox_account || '')}</span></p>
                        <p style="margin: 4px 0;"><strong>Date & Time:</strong> ${escapeHtmlUI(data.searched_at || '')}</p>
                        <p style="margin: 4px 0;"><strong>Job Query:</strong> "${escapeHtmlUI(data.job_description || '')}"</p>
                        <p style="margin: 4px 0;"><strong>Batch Limit:</strong> ${data.batch_size} &nbsp;·&nbsp; <strong>Found:</strong> ${data.results_count}</p>
                        <h4 style="margin-top: 16px; margin-bottom: 8px; color: var(--text-primary); font-size: 0.95rem;">Candidates Returned (${data.results_count}):</h4>
                        ${candHtml}
                    </div>
                    <div style="text-align: right; margin-top: 20px; border-top: 1px solid var(--border); padding-top: 12px;">
                        <button type="button" onclick="closeHistoryDetailsModal()" style="background: var(--accent); color: white; border: none; padding: 6px 16px; border-radius: var(--radius-sm); font-weight: 600; cursor: pointer;">Close</button>
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
