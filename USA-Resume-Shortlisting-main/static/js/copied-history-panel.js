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
    if (isNaN(d.getTime())) return '';

    const dateStr = d.toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric'
    });
    const timeStr = d.toLocaleTimeString('en-US', {
        hour: 'numeric', minute: '2-digit'
    });

    return `🕒 ${dateStr}, ${timeStr}`;
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

function setCopiedFilter(filterKey) {
    window._copiedFilter = filterKey;
    try {
        localStorage.setItem('copied_history_filter', filterKey);
    } catch (e) {}
    fetchCopiedHistoryPanel();
}

function fetchCopiedHistoryPanel() {
    const content = document.getElementById('copied-panel-content');
    const mailboxFilter = document.getElementById('copied-mailbox-filter')?.value || document.getElementById('account_email')?.value || '';
    const days = window._copiedDaysFilter || 30;
    const currentFilter = window._copiedFilter || localStorage.getItem('copied_history_filter') || 'all';
    window._copiedFilter = currentFilter;

    if (!content) return;
    content.innerHTML = '<div style="text-align:center; padding: 24px; color: var(--text-muted);">⏳ Loading candidates...</div>';

    let url = `/api/copied-history?days=${days}&filter=${encodeURIComponent(currentFilter)}`;
    if (mailboxFilter) {
        url += `&mailbox=${encodeURIComponent(mailboxFilter)}`;
    }

    fetch(url)
        .then(res => res.json())
        .then(data => {
            window._copiedData = data;
            const summaryUrl = `/api/copied-history/summary?mailbox=${encodeURIComponent(mailboxFilter)}`;
            fetch(summaryUrl)
                .then(r => r.json())
                .then(summaryData => {
                    window._copiedDataSummary = summaryData;
                    renderCopiedHistoryContent(summaryData);
                })
                .catch(() => {
                    window._copiedDataSummary = { this_week: 0, today: 0, total: 0, never_used: 0 };
                    renderCopiedHistoryContent(window._copiedDataSummary);
                });
        })
        .catch(err => {
            console.error('Error fetching copied history:', err);
            content.innerHTML = '<div style="text-align:center; padding: 20px; color: var(--danger);">Failed to load candidates.</div>';
        });
}

function setCopiedDays(d) {
    window._copiedDaysFilter = d;
    fetchCopiedHistoryPanel();
}

function toggleCopiedDuplicates(show) {
    window._copiedShowDuplicates = show;
    try {
        localStorage.setItem('pref_copied_show_dups', show ? 'true' : 'false');
    } catch(e) {}
    renderCopiedHistoryContent(window._copiedDataSummary);
}

function renderCopiedHistoryContent(summary) {
    try {
        const content = document.getElementById('copied-panel-content');
        if (!content) return;

        const data = window._copiedData || {};
        const showDups = window._copiedShowDuplicates === true;
        const currentFilter = window._copiedFilter || localStorage.getItem('copied_history_filter') || 'all';
        const entries = showDups ? (data.raw_history || data.history || data.entries || []) : (data.history || data.entries || []);

        const totalCopied = (summary && summary.total) || 0;
        const totalNeverUsed = (summary && summary.never_used) || 0;
        const totalToday = (summary && summary.today) || 0;
        const totalWeek = (summary && summary.this_week) || 0;

        // Stat cards HTML
        let statCardsHtml = `
            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 14px;">
                <div onclick="setCopiedFilter('all')" style="background: var(--bg-card); border: ${currentFilter === 'all' || currentFilter === '30d' ? '2px solid #4F46E5' : '1px solid var(--border)'}; border-radius: var(--radius-md); padding: 8px 6px; cursor: pointer; text-align: center; transition: all 0.2s;">
                    <div style="font-size: 1rem; font-weight: 700; color: var(--text-primary);">📋 ${totalCopied}</div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary); margin-top: 2px;">Copied (30d)</div>
                </div>
                <div onclick="setCopiedFilter('never_used')" style="background: var(--bg-card); border: ${currentFilter === 'never_used' ? '2px solid #4F46E5' : '1px solid var(--border)'}; border-radius: var(--radius-md); padding: 8px 6px; cursor: pointer; text-align: center; transition: all 0.2s;">
                    <div style="font-size: 1rem; font-weight: 700; color: #4F46E5;">🎯 ${totalNeverUsed}</div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary); margin-top: 2px;">Seen, not copied</div>
                </div>
                <div onclick="setCopiedFilter('today')" style="background: var(--bg-card); border: ${currentFilter === 'today' ? '2px solid #4F46E5' : '1px solid var(--border)'}; border-radius: var(--radius-md); padding: 8px 6px; cursor: pointer; text-align: center; transition: all 0.2s;">
                    <div style="font-size: 1rem; font-weight: 700; color: #059669;">📅 ${totalToday}</div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary); margin-top: 2px;">Today</div>
                </div>
                <div onclick="setCopiedFilter('7d')" style="background: var(--bg-card); border: ${currentFilter === '7d' ? '2px solid #4F46E5' : '1px solid var(--border)'}; border-radius: var(--radius-md); padding: 8px 6px; cursor: pointer; text-align: center; transition: all 0.2s;">
                    <div style="font-size: 1rem; font-weight: 700; color: #D97706;">⏱️ ${totalWeek}</div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary); margin-top: 2px;">This week</div>
                </div>
            </div>
        `;

        // Filter Pills HTML
        const filtersList = [
            { key: 'all', label: 'All' },
            { key: 'used', label: 'Used' },
            { key: 'never_used', label: 'Never Used' },
            { key: 'today', label: 'Today' },
            { key: '7d', label: '7d' },
            { key: '30d', label: '30d' }
        ];

        let pillsHtml = `
            <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 14px; align-items: center;">
                <span style="font-size: 0.78rem; font-weight: 600; color: var(--text-muted);">Filter by:</span>
        `;
        filtersList.forEach(f => {
            const isActive = currentFilter === f.key;
            pillsHtml += `
                <button type="button" onclick="setCopiedFilter('${f.key}')" style="padding: 4px 12px; border-radius: 9999px; font-size: 0.78rem; font-weight: 600; cursor: pointer; border: 1px solid ${isActive ? '#4F46E5' : 'var(--border)'}; ${isActive ? 'background: #4F46E5; color: white;' : 'background: var(--bg-card); color: var(--text-primary);'} transition: all 0.2s;">
                    ${f.label}
                </button>
            `;
        });
        pillsHtml += `</div>`;

        // Empty state messaging per filter
        const emptyStateMessages = {
            'used': "You haven't copied any candidates yet.",
            'never_used': "All candidates you've seen have been copied. 🎉",
            'today': "No copies yet today.",
            '7d': "No copies in the last 7 days.",
            '30d': "No copies in the last 30 days.",
            'all': "No copied trainers yet."
        };

        if (!entries || entries.length === 0) {
            const emptyMsg = emptyStateMessages[currentFilter] || "No candidate records match this filter.";
            content.innerHTML = `
                ${statCardsHtml}
                ${pillsHtml}
                <div style="text-align: center; padding: 48px 16px;">
                    <div style="font-size: 3rem; margin-bottom: 12px;">📋</div>
                    <h4 style="font-weight: 700; color: var(--text-primary); margin: 0 0 6px 0;">${emptyMsg}</h4>
                    <p style="color: var(--text-muted); font-size: 0.88rem; margin: 0;">Try selecting a different filter above.</p>
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
            const dateVal = item.copied_at || item.last_seen_at;
            const itemDate = dateVal ? new Date(dateVal) : new Date();
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

        // Header counter title
        const counterTitles = {
            'all': `${entries.length} copied trainers`,
            'used': `${entries.length} already-used trainers`,
            'never_used': `${entries.length} seen but never copied`,
            'today': `${entries.length} copied today`,
            '7d': `${entries.length} copied in past 7 days`,
            '30d': `${entries.length} copied in past 30 days`
        };
        const headerTitle = counterTitles[currentFilter] || `${entries.length} candidates`;

        let html = `
            ${statCardsHtml}
            ${pillsHtml}

            <div style="margin-bottom: 12px; font-weight: 700; font-size: 0.9rem; color: var(--text-primary); display: flex; justify-content: space-between; align-items: center;">
                <span>📊 ${headerTitle}</span>
                <a href="/api/copied-history/export" class="btn-icon-subtle" style="text-decoration: none; font-size: 0.8rem;" download>📥 Export CSV</a>
            </div>

            ${currentFilter !== 'never_used' ? `
            <div style="margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; background: var(--bg-card); padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border);">
                <label style="font-size: 0.82rem; font-weight: 600; color: var(--text-secondary); cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">
                    <input type="checkbox" id="chk-show-duplicates" ${showDups ? 'checked' : ''} onchange="toggleCopiedDuplicates(this.checked)" style="cursor: pointer;">
                    Show duplicates ${data.raw_total ? `(${data.raw_total} total)` : ''}
                </label>
                <div style="display: flex; gap: 6px;">
                    <button type="button" onclick="setCopiedDays(7)" style="padding: 3px 8px; font-size: 0.78rem; border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--bg-primary); cursor: pointer;">Last 7d</button>
                    <button type="button" onclick="setCopiedDays(30)" style="padding: 3px 8px; font-size: 0.78rem; border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--bg-primary); cursor: pointer;">Last 30d</button>
                </div>
            </div>
            ` : ''}

            <div style="margin-bottom: 14px;">
                <input type="text" id="copied-search-input" oninput="filterCopiedCards()" placeholder="Filter by name or email..." class="form-input" style="padding: 6px 12px; font-size: 0.85rem; width: 100%;">
            </div>

            <div id="copied-cards-list" style="display: flex; flex-direction: column; gap: 20px;">
        `;

        ['Today', 'Yesterday', 'This Week', 'Older'].forEach(groupKey => {
            const items = groups[groupKey];
            if (items && items.length > 0) {
                html += `
                    <div>
                        <div style="font-weight: 700; font-size: 0.85rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 4px;">
                            ── ${groupKey.toUpperCase()} (${items.length}) ──
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 10px;">
                `;

                items.forEach(c => {
                    const dateVal = c.copied_at || c.last_seen_at;
                    const timeStr = formatTimestamp(dateVal) || new Date(dateVal).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    
                    let countBadge = '';
                    if (!showDups && c.copy_count && c.copy_count > 1) {
                        let tooltip = `Last copied ${timeStr}`;
                        if (c.all_timestamps && c.all_timestamps.length > 1) {
                            const others = c.all_timestamps.slice(1).map(ts => formatTimestamp(ts));
                            tooltip += `. Also copied: ${others.join('; ')}`;
                        }
                        countBadge = `<span class="tag-copy-count" style="background: #e0e7ff; color: #3730a3; font-size: 0.75rem; font-weight: 700; padding: 2px 7px; border-radius: 10px; margin-left: 6px;" title="${escapeHtml(tooltip)}">[× ${c.copy_count}]</span>`;
                    }

                    if (c.never_used || currentFilter === 'never_used') {
                        countBadge = `<span style="background: #fef3c7; color: #92400e; font-size: 0.72rem; font-weight: 700; padding: 2px 7px; border-radius: 10px; margin-left: 6px;">[Uncopied]</span>`;
                    }

                    html += `
                        <div class="copied-card" data-search-text="${escapeHtml(c.candidate_name || '')} ${escapeHtml(c.candidate_email || '')} ${escapeHtml(c.candidate_phone || '')} ${escapeHtml(c.mailbox_account || '')} ${escapeHtml(c.job_description || '')}" style="background: var(--bg-primary); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px 14px; font-size: 0.88rem;">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px;">
                                <strong style="color: var(--text-primary); font-size: 0.92rem; display: inline-flex; align-items: center;">
                                    👤 ${escapeHtml(c.candidate_name || 'Candidate')} ${countBadge}
                                </strong>
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
    const rawInput = document.getElementById('copied-search-input')?.value.toLowerCase().trim() || '';
    const cards = document.querySelectorAll('.copied-card');
    
    if (!rawInput) {
        cards.forEach(card => {
            card.style.display = 'block';
        });
        return;
    }

    // Split input query into tokens by whitespace, commas, semicolons, or newlines
    const terms = rawInput.split(/[\s,;\n\r]+/).filter(Boolean);

    cards.forEach(card => {
        const searchVal = card.getAttribute('data-search-text')?.toLowerCase() || '';
        // Match if exact query is found OR if ANY individual email/keyword token matches
        const isMatch = searchVal.includes(rawInput) || terms.some(term => searchVal.includes(term));
        card.style.display = isMatch ? 'block' : 'none';
    });
}
