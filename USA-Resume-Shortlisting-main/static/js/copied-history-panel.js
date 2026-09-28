// Safe HTML escape for user-provided text
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
window.escapeHtml = escapeHtml;

function formatTimestamp(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    const isYesterday = d.toDateString() === yesterday.toDateString();

    const time = d.toLocaleTimeString('en-US', {
        hour: 'numeric', minute: '2-digit'
    });

    if (isToday) return `🕒 ${time}`;
    if (isYesterday) return `🕒 Yesterday, ${time}`;

    return `🕒 ${d.toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric'
    })}, ${time}`;
}

document.addEventListener('DOMContentLoaded', function () {
    updateCopiedHistoryBadge();

    const btn = document.getElementById('btn-copied-panel');
    const panel = document.getElementById('copied-side-panel');
    const overlay = document.getElementById('copied-panel-overlay');
    const closeBtn = document.getElementById('btn-close-copied');

    if (btn && panel && overlay) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            panel.classList.add('active');
            overlay.classList.add('active');
            fetchCopiedHistoryPanel();
        });
    }

    if (closeBtn && panel && overlay) {
        closeBtn.addEventListener('click', closeCopiedPanel);
        overlay.addEventListener('click', closeCopiedPanel);
    }
});

function closeCopiedPanel() {
    const panel = document.getElementById('copied-side-panel');
    const overlay = document.getElementById('copied-panel-overlay');
    if (panel) panel.classList.remove('active');
    if (overlay) overlay.classList.remove('active');
}

function updateCopiedHistoryBadge() {
    const badge = document.getElementById('copied-history-badge');
    const mailbox = document.getElementById('account_email')?.value || '';

    fetch(`/api/copied-history/summary?mailbox=${encodeURIComponent(mailbox)}`)
        .then(res => res.json())
        .then(data => {
            if (badge) {
                const count = data.this_week || 0;
                if (count > 0) {
                    badge.textContent = count;
                    badge.style.display = 'inline-flex';
                } else {
                    badge.style.display = 'none';
                }
            }
        })
        .catch(err => console.error('Error updating copied history badge:', err));
}

function fetchCopiedHistoryPanel() {
    const content = document.getElementById('copied-panel-content');
    const mailboxFilter = document.getElementById('copied-mailbox-filter')?.value || '';
    const days = window._copiedDaysFilter || 30;

    if (!content) return;
    content.innerHTML = '<div style="text-align:center; padding: 24px; color: var(--text-muted);">⏳ Loading copied history...</div>';

    let url = `/api/copied-history?days=${days}`;
    if (mailboxFilter) {
        url += `&mailbox=${encodeURIComponent(mailboxFilter)}`;
    }

    fetch(url)
        .then(res => res.json())
        .then(data => {
            const summaryUrl = `/api/copied-history/summary?mailbox=${encodeURIComponent(mailboxFilter)}`;
            fetch(summaryUrl)
                .then(r => r.json())
                .then(summaryData => {
                    renderCopiedHistoryContent(data.history || [], summaryData);
                })
                .catch(() => renderCopiedHistoryContent(data.history || [], { this_week: 0, today: 0, total: 0 }));
        })
        .catch(err => {
            console.error('Error fetching copied history:', err);
            content.innerHTML = '<div style="text-align:center; padding: 20px; color: var(--danger);">Failed to load copied history.</div>';
        });
}

function setCopiedDays(d) {
    window._copiedDaysFilter = d;
    fetchCopiedHistoryPanel();
}

function renderCopiedHistoryContent(entries, summary) {
    try {
        const content = document.getElementById('copied-panel-content');
        if (!content) return;

        if (!entries || entries.length === 0) {
            content.innerHTML = `
                <div style="text-align: center; padding: 48px 16px;">
                    <div style="font-size: 3rem; margin-bottom: 12px;">📋</div>
                    <h4 style="font-weight: 700; color: var(--text-primary); margin: 0 0 6px 0;">No copied trainers yet</h4>
                    <p style="color: var(--text-muted); font-size: 0.88rem; margin: 0;">When you copy a candidate's details, they'll appear here.</p>
                </div>
            `;
            return;
        }

        // Group entries: Today, Yesterday, This Week, Older
        const groups = {
            'Today': [],
            'Yesterday': [],
            'This Week': [],
            'Older': []
        };

        const now = new Date();
        const todayStr = now.toDateString();
        const yesterday = new Date(now);
        yesterday.setDate(yesterday.getDate() - 1);
        const yesterdayStr = yesterday.toDateString();
        const weekAgo = new Date(now);
        weekAgo.setDate(weekAgo.getDate() - 7);

        entries.forEach(item => {
            const itemDate = new Date(item.copied_at);
            const itemDateStr = itemDate.toDateString();

            if (itemDateStr === todayStr) {
                groups['Today'].push(item);
            } else if (itemDateStr === yesterdayStr) {
                groups['Yesterday'].push(item);
            } else if (itemDate >= weekAgo) {
                groups['This Week'].push(item);
            } else {
                groups['Older'].push(item);
            }
        });

        let html = `
            <div style="margin-bottom: 16px; font-weight: 600; font-size: 0.88rem; color: var(--text-secondary); display: flex; justify-content: space-between; align-items: center;">
                <span>📊 ${(summary && summary.this_week) || 0} copies this week &nbsp;·&nbsp; ${(summary && summary.today) || 0} today</span>
                <a href="/api/copied-history/export" class="btn-icon-subtle" style="text-decoration: none; font-size: 0.8rem;" download>📥 Export CSV</a>
            </div>

            <div style="margin-bottom: 16px; display: flex; gap: 8px; flex-wrap: wrap;">
                <input type="text" id="copied-search-input" oninput="filterCopiedCards()" placeholder="Filter by name or email..." class="form-input" style="padding: 6px 12px; font-size: 0.85rem; flex: 1;">
                <button type="button" onclick="setCopiedDays(7)" style="padding: 4px 10px; font-size: 0.8rem; border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--bg-primary); cursor: pointer;">Last 7d</button>
                <button type="button" onclick="setCopiedDays(30)" style="padding: 4px 10px; font-size: 0.8rem; border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--bg-primary); cursor: pointer;">Last 30d</button>
            </div>

            <div id="copied-cards-list" style="display: flex; flex-direction: column; gap: 20px;">
        `;

        ['Today', 'Yesterday', 'This Week', 'Older'].forEach(groupKey => {
            const items = groups[groupKey];
            if (items && items.length > 0) {
                html += `
                    <div>
                        <div style="font-weight: 700; font-size: 0.85rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 4px;">
                            ── ${groupKey} (${items.length}) ──
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 10px;">
                `;

                items.forEach(c => {
                    const timeStr = formatTimestamp(c.copied_at) || new Date(c.copied_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    html += `
                        <div class="copied-card" data-search-text="${escapeHtml(c.candidate_name || '')} ${escapeHtml(c.candidate_email || '')}" style="background: var(--bg-primary); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px 14px; font-size: 0.88rem;">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px;">
                                <strong style="color: var(--text-primary); font-size: 0.92rem;">👤 ${escapeHtml(c.candidate_name || 'Candidate')}</strong>
                                <span style="color: var(--text-muted); font-size: 0.78rem;">${timeStr}</span>
                            </div>
                            <div style="color: var(--text-secondary); margin-bottom: 2px;">📧 ${escapeHtml(c.candidate_email || 'N/A')}</div>
                            ${c.candidate_phone ? `<div style="color: var(--text-secondary); margin-bottom: 2px;">📞 ${escapeHtml(c.candidate_phone)}</div>` : ''}
                            <div style="color: var(--text-muted); font-size: 0.8rem; margin-top: 4px;">📬 Mail: ${escapeHtml(c.mailbox_account || '')}</div>
                            ${c.job_description ? `<div style="color: var(--accent); font-size: 0.8rem; font-weight: 600;">🔍 Search: "${escapeHtml(c.job_description)}"</div>` : ''}
                        </div>
                    `;
                });

                html += `
                        </div>
                    </div>
                `;
            }
        });

        html += `</div>`;
        content.innerHTML = html;
    } catch (err) {
        console.error('[copied-history-panel] render failed:', err);
        const container = document.getElementById('copied-panel-content') || document.getElementById('copied-history-body');
        if (container) {
            container.innerHTML = `
                <div style="padding: 24px; text-align: center; color: #64748B;">
                    ⚠️ Failed to render entries. 
                    <button onclick="fetchCopiedHistoryPanel()" style="margin-left: 8px; padding: 4px 12px;">
                        Retry
                    </button>
                </div>
            `;
        }
    }
}

function filterCopiedCards() {
    const text = document.getElementById('copied-search-input')?.value.toLowerCase().trim() || '';
    const cards = document.querySelectorAll('.copied-card');
    cards.forEach(card => {
        const searchVal = card.getAttribute('data-search-text')?.toLowerCase() || '';
        if (!text || searchVal.includes(text)) {
            card.style.display = 'block';
        } else {
            card.style.display = 'none';
        }
    });
}
