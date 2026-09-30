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

// Client-side local timezone date range calculation
function getDateBounds(period, customFrom, customTo) {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

    const formatDate = (d) => {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${y}-${m}-${day}`;
    };

    let fromDate = today;
    let toDate = today;

    if (period === 'today') {
        fromDate = today;
        toDate = today;
    } else if (period === 'yesterday') {
        const yest = new Date(today);
        yest.setDate(yest.getDate() - 1);
        fromDate = yest;
        toDate = yest;
    } else if (period === '7d') {
        const start = new Date(today);
        start.setDate(start.getDate() - 6);
        fromDate = start;
        toDate = today;
    } else if (period === '14d') {
        const start = new Date(today);
        start.setDate(start.getDate() - 13);
        fromDate = start;
        toDate = today;
    } else if (period === '30d') {
        const start = new Date(today);
        start.setDate(start.getDate() - 29);
        fromDate = start;
        toDate = today;
    } else if (period === 'custom') {
        const fallback7d = new Date(today);
        fallback7d.setDate(fallback7d.getDate() - 6);
        return {
            from: customFrom || formatDate(fallback7d),
            to: customTo || formatDate(today)
        };
    } else {
        const start = new Date(today);
        start.setDate(start.getDate() - 29);
        fromDate = start;
        toDate = today;
    }

    return {
        from: formatDate(fromDate),
        to: formatDate(toDate)
    };
}

// In-memory 60s cache
window._copiedCache = window._copiedCache || {};

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

function setCopiedFilter(mode, period) {
    if (mode) {
        window._copiedMode = mode;
        try { localStorage.setItem('copied_history_mode', mode); } catch (e) {}
    }
    if (period) {
        window._copiedPeriod = period;
        try { localStorage.setItem('copied_history_period', period); } catch (e) {}
    }
    fetchCopiedHistoryPanel();
}

function setCopiedMode(mode) {
    window._copiedMode = mode;
    try { localStorage.setItem('copied_history_mode', mode); } catch (e) {}
    fetchCopiedHistoryPanel();
}

function setCopiedPeriod(period) {
    if (period === 'all') {
        window._copiedMode = 'copied';
        window._copiedPeriod = 'all';
    } else if (period === 'used') {
        window._copiedMode = 'copied';
        window._copiedPeriod = 'used';
    } else if (period === 'never_used' || period === 'never') {
        window._copiedMode = 'not_copied';
        window._copiedPeriod = 'never_used';
    } else {
        window._copiedPeriod = period;
    }

    try {
        localStorage.setItem('copied_history_mode', window._copiedMode);
        localStorage.setItem('copied_history_period', window._copiedPeriod);
    } catch (e) {}

    fetchCopiedHistoryPanel();
}

function applyCustomDateRange() {
    const fromInput = document.getElementById('custom-date-from')?.value;
    const toInput = document.getElementById('custom-date-to')?.value;

    if (!fromInput || !toInput) {
        if (typeof showToast === 'function') showToast('⚠️ Please select both From and To dates.', true);
        return;
    }

    if (fromInput > toInput) {
        if (typeof showToast === 'function') showToast("⚠️ 'From' date must be on or before 'To' date.", true);
        return;
    }

    window._copiedCustomFrom = fromInput;
    window._copiedCustomTo = toInput;
    window._copiedPeriod = 'custom';

    try {
        localStorage.setItem('copied_history_from', fromInput);
        localStorage.setItem('copied_history_to', toInput);
        localStorage.setItem('copied_history_period', 'custom');
    } catch (e) {}

    fetchCopiedHistoryPanel();
}

function cancelCustomDateRange() {
    window._copiedPeriod = '30d';
    try { localStorage.setItem('copied_history_period', '30d'); } catch (e) {}
    fetchCopiedHistoryPanel();
}

function toggleCopiedDuplicates(show) {
    window._copiedShowDuplicates = show;
    try {
        localStorage.setItem('pref_copied_show_dups', show ? 'true' : 'false');
    } catch (e) {}
    renderCopiedHistoryContent(window._copiedDataSummary);
}

function refreshCopiedHistoryPanel() {
    // Invalidate cache
    window._copiedCache = {};
    fetchCopiedHistoryPanel();
}

function fetchCopiedHistoryPanel() {
    const content = document.getElementById('copied-panel-content');
    const mailboxFilter = document.getElementById('copied-mailbox-filter')?.value || document.getElementById('account_email')?.value || '';

    // Restore state from localStorage if not set
    const mode = window._copiedMode || localStorage.getItem('copied_history_mode') || 'copied';
    const period = window._copiedPeriod || localStorage.getItem('copied_history_period') || '30d';
    const customFrom = window._copiedCustomFrom || localStorage.getItem('copied_history_from') || '';
    const customTo = window._copiedCustomTo || localStorage.getItem('copied_history_to') || '';

    window._copiedMode = mode;
    window._copiedPeriod = period;

    const dateBounds = getDateBounds(period, customFrom, customTo);
    window._copiedFrom = dateBounds.from;
    window._copiedTo = dateBounds.to;

    if (!content) return;

    // Render skeleton loader
    content.innerHTML = `
        <div style="padding: 16px;">
            <div class="skeleton-pulse" style="height: 48px; border-radius: var(--radius-md); margin-bottom: 14px; background: var(--border);"></div>
            <div class="skeleton-pulse" style="height: 36px; border-radius: 9999px; margin-bottom: 14px; background: var(--border);"></div>
            <div class="skeleton-pulse" style="height: 72px; border-radius: var(--radius-md); margin-bottom: 10px; background: var(--border);"></div>
            <div class="skeleton-pulse" style="height: 72px; border-radius: var(--radius-md); margin-bottom: 10px; background: var(--border);"></div>
        </div>
    `;

    const cacheKey = `${mailboxFilter}_${mode}_${period}_${dateBounds.from}_${dateBounds.to}`;
    const nowTs = Date.now();

    // Check 60s cache
    if (window._copiedCache[cacheKey] && (nowTs - window._copiedCache[cacheKey].timestamp < 60000)) {
        window._copiedData = window._copiedCache[cacheKey].data;
        fetchSummaryAndRender(mailboxFilter);
        return;
    }

    let url = `/api/copied-history?mode=${encodeURIComponent(mode)}&period_label=${encodeURIComponent(period)}&from=${encodeURIComponent(dateBounds.from)}&to=${encodeURIComponent(dateBounds.to)}`;
    if (mailboxFilter) {
        url += `&mailbox=${encodeURIComponent(mailboxFilter)}`;
    }

    fetch(url)
        .then(res => res.json())
        .then(data => {
            window._copiedData = data;
            window._copiedCache[cacheKey] = {
                timestamp: nowTs,
                data: data
            };
            fetchSummaryAndRender(mailboxFilter);
        })
        .catch(err => {
            console.error('Error fetching copied history:', err);
            content.innerHTML = '<div style="text-align:center; padding: 20px; color: var(--danger);">Failed to load candidates.</div>';
        });
}

function fetchSummaryAndRender(mailboxFilter) {
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
}

function formatHeaderTitle(count, mode, period, fromDateStr, toDateStr) {
    const formattedCount = (count || 0).toLocaleString('en-US');
    const isCopied = mode === 'copied';
    const icon = isCopied ? '📋' : '🎯';

    const formatDateObj = (dateStr) => {
        if (!dateStr) return '';
        const parts = dateStr.split('-');
        if (parts.length !== 3) return dateStr;
        const d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    };

    const fromFormatted = formatDateObj(fromDateStr);
    const toFormatted = formatDateObj(toDateStr);

    if (period === 'today') {
        const pText = isCopied ? 'copied today' : 'seen but not copied today';
        return `${icon} ${formattedCount} ${pText} (${toFormatted})`;
    }
    if (period === 'yesterday') {
        const pText = isCopied ? 'copied yesterday' : 'seen but not copied yesterday';
        return `${icon} ${formattedCount} ${pText} (${fromFormatted})`;
    }
    if (period === '7d') {
        const pText = isCopied ? 'copied in the last 7 days' : 'seen but not copied in the last 7 days';
        return `${icon} ${formattedCount} ${pText} (${fromFormatted} – ${toFormatted})`;
    }
    if (period === '14d') {
        const pText = isCopied ? 'copied in the last 14 days' : 'seen but not copied in the last 14 days';
        return `${icon} ${formattedCount} ${pText} (${fromFormatted} – ${toFormatted})`;
    }
    if (period === '30d') {
        const pText = isCopied ? 'copied in the last 30 days' : 'seen but not copied in the last 30 days';
        return `${icon} ${formattedCount} ${pText} (${fromFormatted} – ${toFormatted})`;
    }
    if (period === 'custom') {
        const pText = isCopied ? 'copied in date range' : 'seen but not copied in date range';
        return `${icon} ${formattedCount} ${pText} (${fromFormatted} – ${toFormatted})`;
    }
    if (period === 'used') {
        return `📋 ${formattedCount} already-used trainers`;
    }
    if (period === 'never_used' || period === 'never') {
        return `🎯 ${formattedCount} seen but never copied`;
    }
    return isCopied ? `📋 ${formattedCount} copied trainers` : `🎯 ${formattedCount} uncopied trainers`;
}

function renderCopiedHistoryContent(summary) {
    try {
        const content = document.getElementById('copied-panel-content');
        if (!content) return;

        const data = window._copiedData || {};
        const mode = window._copiedMode || 'copied';
        const period = window._copiedPeriod || '30d';
        const showDups = window._copiedShowDuplicates === true;
        const entries = showDups ? (data.raw_history || data.history || data.entries || []) : (data.history || data.entries || []);

        const totalCopied = (summary && summary.total) || 0;
        const totalNeverUsed = (summary && summary.never_used) || 0;
        const totalToday = (summary && summary.today) || 0;
        const totalWeek = (summary && summary.this_week) || 0;

        // Stat cards HTML with active shortcut highlighting
        const isCard1Active = mode === 'copied' && period === '30d';
        const isCard2Active = mode === 'not_copied' && (period === '30d' || period === 'never_used');
        const isCard3Active = mode === 'copied' && period === 'today';
        const isCard4Active = mode === 'copied' && period === '7d';

        let statCardsHtml = `
            <div class="copied-stat-grid">
                <div onclick="setCopiedFilter('copied', '30d')" class="copied-stat-card ${isCard1Active ? 'active' : ''}">
                    <div style="font-size: 1rem; font-weight: 700; color: var(--text-primary);">📋 ${totalCopied.toLocaleString()}</div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary); margin-top: 2px;">Copied (30d)</div>
                </div>
                <div onclick="setCopiedFilter('not_copied', '30d')" class="copied-stat-card ${isCard2Active ? 'active' : ''}">
                    <div style="font-size: 1rem; font-weight: 700; color: #4F46E5;">🎯 ${totalNeverUsed.toLocaleString()}</div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary); margin-top: 2px;">Seen, not copied</div>
                </div>
                <div onclick="setCopiedFilter('copied', 'today')" class="copied-stat-card ${isCard3Active ? 'active' : ''}">
                    <div style="font-size: 1rem; font-weight: 700; color: #059669;">📅 ${totalToday.toLocaleString()}</div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary); margin-top: 2px;">Today</div>
                </div>
                <div onclick="setCopiedFilter('copied', '7d')" class="copied-stat-card ${isCard4Active ? 'active' : ''}">
                    <div style="font-size: 1rem; font-weight: 700; color: #D97706;">⏱️ ${totalWeek.toLocaleString()}</div>
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
            { key: 'yesterday', label: 'Yesterday' },
            { key: '7d', label: '7d' },
            { key: '14d', label: '14d' },
            { key: '30d', label: '30d' },
            { key: 'custom', label: 'Custom' }
        ];

        let pillsHtml = `
            <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; align-items: center;">
                <span style="font-size: 0.78rem; font-weight: 600; color: var(--text-muted);">Filter by:</span>
        `;
        filtersList.forEach(f => {
            const isActive = period === f.key;
            pillsHtml += `
                <button type="button" onclick="setCopiedPeriod('${f.key}')" style="padding: 4px 12px; border-radius: 9999px; font-size: 0.78rem; font-weight: 600; cursor: pointer; border: 1px solid ${isActive ? '#4F46E5' : 'var(--border)'}; ${isActive ? 'background: #4F46E5; color: white;' : 'background: var(--bg-card); color: var(--text-primary);'} transition: all 0.2s;">
                    ${f.label}
                </button>
            `;
        });
        pillsHtml += `</div>`;

        // Universal Copied / Not Copied Toggle Row
        let modeToggleHtml = `
            <div class="mode-toggle-row">
                <span style="font-size: 0.78rem; font-weight: 600; color: var(--text-muted);">Show:</span>
                <button type="button" onclick="setCopiedMode('copied')" class="btn-mode-toggle ${mode === 'copied' ? 'active' : ''}">
                    ${mode === 'copied' ? '◉' : '○'} Copied
                </button>
                <button type="button" onclick="setCopiedMode('not_copied')" class="btn-mode-toggle ${mode === 'not_copied' ? 'active' : ''}">
                    ${mode === 'not_copied' ? '◉' : '○'} Not copied
                </button>
            </div>
        `;

        // Custom Date Range Box HTML
        let customDateBoxHtml = '';
        if (period === 'custom') {
            const bounds = getDateBounds('custom', window._copiedCustomFrom, window._copiedCustomTo);
            customDateBoxHtml = `
                <div class="custom-date-box">
                    <div style="font-weight: 700; font-size: 0.85rem; color: var(--text-primary); margin-bottom: 8px;">📅 Custom date range</div>
                    <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 10px;">
                        <label style="font-size: 0.8rem; font-weight: 600; color: var(--text-secondary);">From:
                            <input type="date" id="custom-date-from" value="${escapeHtml(bounds.from)}" class="form-input" style="padding: 4px 8px; font-size: 0.82rem; margin-left: 4px;">
                        </label>
                        <label style="font-size: 0.8rem; font-weight: 600; color: var(--text-secondary);">To:
                            <input type="date" id="custom-date-to" value="${escapeHtml(bounds.to)}" class="form-input" style="padding: 4px 8px; font-size: 0.82rem; margin-left: 4px;">
                        </label>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <button type="button" onclick="applyCustomDateRange()" style="padding: 4px 14px; font-size: 0.8rem; font-weight: 700; background: #4F46E5; color: white; border: none; border-radius: var(--radius-md); cursor: pointer;">Apply</button>
                        <button type="button" onclick="cancelCustomDateRange()" style="padding: 4px 12px; font-size: 0.8rem; font-weight: 600; background: var(--bg-card); color: var(--text-secondary); border: 1px solid var(--border); border-radius: var(--radius-md); cursor: pointer;">Cancel</button>
                    </div>
                </div>
            `;
        }

        // Empty state messaging per mode and filter (Part 13)
        const emptyStateMessages = {
            'copied_today': "📋 You haven't copied any trainers today.",
            'not_copied_today': "🎯 All trainers seen today have been copied. Great work! 🎉",
            'copied_yesterday': "📋 You didn't copy any trainers yesterday.",
            'not_copied_yesterday': "🎯 No uncopied trainers from yesterday.",
            'copied_7d': "📋 No trainers copied in the last 7 days.",
            'not_copied_7d': "🎯 All trainers from the last 7 days have been copied. Great work! 🎉",
            'copied_14d': "📋 No trainers copied in the last 14 days.",
            'not_copied_14d': "🎯 All trainers from the last 14 days have been copied. Great work! 🎉",
            'copied_30d': "📋 No trainers copied in the last 30 days.",
            'not_copied_30d': "🎯 No uncopied trainers found in the last 30 days.",
            'copied_custom': "📋 No trainers copied in this date range.",
            'not_copied_custom': "🎯 No seen-but-not-copied trainers in this date range.",
            'copied_used': "You haven't copied any candidates yet.",
            'not_copied_never_used': "All candidates you've seen have been copied. 🎉",
            'copied_all': "No copied trainers yet."
        };

        const stateKey = `${mode}_${period}`;
        const emptyMsg = emptyStateMessages[stateKey] || (mode === 'copied' ? "No copied trainers match this filter." : "No uncopied trainers match this filter.");

        if (!entries || entries.length === 0) {
            content.innerHTML = `
                ${statCardsHtml}
                <div style="background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px; margin-bottom: 14px;">
                    ${pillsHtml}
                    ${modeToggleHtml}
                </div>
                ${customDateBoxHtml}
                <div style="text-align: center; padding: 40px 16px;">
                    <div style="font-size: 2.8rem; margin-bottom: 10px;">${mode === 'copied' ? '📋' : '🎯'}</div>
                    <h4 style="font-weight: 700; color: var(--text-primary); margin: 0 0 6px 0;">${emptyMsg}</h4>
                    <p style="color: var(--text-muted); font-size: 0.85rem; margin: 0;">Try selecting a different time filter or mode above.</p>
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

        // Dynamic Header Title
        const headerTitle = formatHeaderTitle(entries.length, mode, period, window._copiedFrom, window._copiedTo);

        let html = `
            ${statCardsHtml}
            <div style="background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px; margin-bottom: 14px;">
                ${pillsHtml}
                ${modeToggleHtml}
            </div>
            ${customDateBoxHtml}

            <div style="margin-bottom: 12px; font-weight: 700; font-size: 0.88rem; color: var(--text-primary); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <span>${headerTitle}</span>
                <a href="/api/copied-history/export" class="btn-icon-subtle" style="text-decoration: none; font-size: 0.8rem;" download>📥 Export CSV</a>
            </div>

            ${mode === 'copied' ? `
            <div style="margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; background: var(--bg-card); padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border);">
                <label style="font-size: 0.82rem; font-weight: 600; color: var(--text-secondary); cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">
                    <input type="checkbox" id="chk-show-duplicates" ${showDups ? 'checked' : ''} onchange="toggleCopiedDuplicates(this.checked)" style="cursor: pointer;">
                    Show duplicates ${data.raw_total ? `(${data.raw_total} total)` : ''}
                </label>
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
                    if (mode === 'copied' && !showDups && c.copy_count && c.copy_count > 1) {
                        let tooltip = `Last copied ${timeStr}`;
                        if (c.all_timestamps && c.all_timestamps.length > 1) {
                            const others = c.all_timestamps.slice(1).map(ts => formatTimestamp(ts));
                            tooltip += `. Also copied: ${others.join('; ')}`;
                        }
                        countBadge = `<span class="tag-copy-count" style="background: #e0e7ff; color: #3730a3; font-size: 0.75rem; font-weight: 700; padding: 2px 7px; border-radius: 10px; margin-left: 6px;" title="${escapeHtml(tooltip)}">[× ${c.copy_count}]</span>`;
                    }

                    if (mode === 'not_copied' || c.never_used) {
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

    const terms = rawInput.split(/[\s,;\n\r]+/).filter(Boolean);

    cards.forEach(card => {
        const searchVal = card.getAttribute('data-search-text')?.toLowerCase() || '';
        const isMatch = searchVal.includes(rawInput) || terms.some(term => searchVal.includes(term));
        card.style.display = isMatch ? 'block' : 'none';
    });
}
