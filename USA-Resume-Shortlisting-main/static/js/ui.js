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

    fetch('/api/search-history?days=30')
        .then(res => res.json())
        .then(data => {
            if (data && data.history && data.history.length > 0) {
                let html = '<div style="display:flex; flex-direction:column; gap: 14px;">';
                data.history.forEach(item => {
                    html += `
                        <div style="background: var(--bg-primary); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 14px;">
                            <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">
                                📅 ${new Date(item.created_at).toLocaleString()}
                            </div>
                            <div style="font-size: 0.85rem; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px;">
                                📬 ${escapeHtmlUI(item.mailbox_account || '')}
                            </div>
                            <div style="font-size: 0.95rem; font-weight: 700; color: var(--accent); margin-bottom: 8px;">
                                "${escapeHtmlUI(item.job_description || '')}"
                            </div>
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <span style="font-size: 0.82rem; color: var(--text-secondary);">
                                    📊 ${item.results_count || 0} candidates
                                </span>
                                <button type="button" onclick="rerunHistorySearch('${escapeHtmlUI(item.job_description || '')}', '${escapeHtmlUI(item.mailbox_account || '')}')" style="background: var(--accent); color: white; border: none; padding: 4px 10px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; cursor: pointer;">
                                    Re-run 🔄
                                </button>
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
