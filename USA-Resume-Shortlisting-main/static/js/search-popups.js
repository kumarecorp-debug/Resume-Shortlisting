/**
 * search-popups.js
 * Implements Feature A (Debounced 'Searched Before' popup),
 * Feature B ('New Candidates Since Last Search' pre-search modal),
 * and Feature C (Autocomplete dropdown on focus).
 */

(function() {
    'use strict';

    let typingTimer = null;
    const DEBOUNCE_DELAY = 500; // ms
    const SUGGESTIONS_CACHE_TTL = 60000; // 60 seconds
    let suggestionsCache = {
        mailbox: null,
        timestamp: 0,
        data: []
    };
    let dismissedJDs = new Set();
    let pendingFormSubmit = false;

    // Relative time formatting helper
    function getRelativeTimeOrDate(isoString) {
        if (!isoString) return '';
        try {
            const date = new Date(isoString.replace('Z', '+00:00'));
            const now = new Date();
            const diffMs = now - date;
            const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
            const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

            if (diffHours < 1) return 'Just now';
            if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
            if (diffDays === 1) return 'Yesterday';
            if (diffDays < 7) return `${diffDays} days ago`;
            if (diffDays < 30) {
                const weeks = Math.floor(diffDays / 7);
                return `${weeks} week${weeks > 1 ? 's' : ''} ago`;
            }
            if (diffDays < 365) {
                const months = Math.floor(diffDays / 30);
                return `${months} month${months > 1 ? 's' : ''} ago`;
            }
            return date.toLocaleDateString();
        } catch (e) {
            return '';
        }
    }

    function formatDateShort(isoString) {
        if (!isoString) return '';
        try {
            const date = new Date(isoString.replace('Z', '+00:00'));
            return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        } catch (e) {
            return isoString.substring(0, 10);
        }
    }

    // DOM Elements & Containers Setup
    function initContainers() {
        const textarea = document.getElementById('job_query');
        if (!textarea) return;

        // Wrap textarea in a relative div if not already wrapped
        let wrapper = textarea.parentElement;
        if (!wrapper.classList.contains('textarea-wrapper')) {
            wrapper = document.createElement('div');
            wrapper.className = 'textarea-wrapper';
            wrapper.style.position = 'relative';
            wrapper.style.width = '100%';
            textarea.parentNode.insertBefore(wrapper, textarea);
            wrapper.appendChild(textarea);
        }

        // Create Autocomplete Suggestions Container if not exists
        if (!document.getElementById('search-suggestions-dropdown')) {
            const dropdown = document.createElement('div');
            dropdown.id = 'search-suggestions-dropdown';
            dropdown.className = 'search-suggestions-dropdown';
            dropdown.style.display = 'none';
            wrapper.appendChild(dropdown);
        }

        // Create Feature A Popup Container if not exists
        if (!document.getElementById('searched-before-popup')) {
            const popup = document.createElement('div');
            popup.id = 'searched-before-popup';
            popup.className = 'searched-before-popup';
            popup.style.display = 'none';
            wrapper.appendChild(popup);
        }

        // Create Feature B Modal Overlay if not exists
        if (!document.getElementById('feature-b-modal-overlay')) {
            const modalOverlay = document.createElement('div');
            modalOverlay.id = 'feature-b-modal-overlay';
            modalOverlay.className = 'feature-b-modal-overlay';
            modalOverlay.style.display = 'none';
            modalOverlay.innerHTML = `
                <div class="feature-b-modal-card">
                    <button type="button" class="feature-b-close-btn" id="feature-b-close">&times;</button>
                    <div class="feature-b-modal-header">
                        <span class="feature-b-icon">🔔</span>
                        <h3 id="feature-b-title">New matching resumes since your last search</h3>
                    </div>
                    <div class="feature-b-modal-body">
                        <p class="feature-b-meta-line">Last search: <strong id="feature-b-last-date">--</strong></p>
                        <p class="feature-b-meta-line">New since then: <span class="badge-new-count" id="feature-b-new-count">0</span> resumes</p>
                        <p class="feature-b-meta-line">Already seen: <strong id="feature-b-seen-count">0</strong> candidates</p>
                    </div>
                    <div class="feature-b-modal-prompt">Choose what to search:</div>
                    <div class="feature-b-modal-actions">
                        <button type="button" class="btn-modal-action btn-new-only" id="feature-b-btn-new">🆕 Search NEW only (<span id="feature-b-btn-new-num">0</span>)</button>
                        <button type="button" class="btn-modal-action btn-everything" id="feature-b-btn-all">🔁 Search everything (<span id="feature-b-btn-all-num">0</span>)</button>
                        <button type="button" class="btn-modal-action btn-cancel" id="feature-b-btn-cancel">Cancel</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modalOverlay);
        }
    }

    // ============================================================
    // FEATURE C: Autocomplete Suggestions
    // ============================================================
    async function fetchSuggestions(mailbox) {
        const now = Date.now();
        if (suggestionsCache.mailbox === mailbox && (now - suggestionsCache.timestamp < SUGGESTIONS_CACHE_TTL)) {
            return suggestionsCache.data;
        }
        try {
            const res = await fetch(`/api/history/suggestions?mailbox=${encodeURIComponent(mailbox)}`);
            if (!res.ok) return [];
            const data = await res.json();
            suggestionsCache = {
                mailbox: mailbox,
                timestamp: now,
                data: Array.isArray(data) ? data : []
            };
            return suggestionsCache.data;
        } catch (e) {
            return [];
        }
    }

    async function showSuggestions() {
        const textarea = document.getElementById('job_query');
        const dropdown = document.getElementById('search-suggestions-dropdown');
        const selectAccount = document.getElementById('account_email');
        if (!textarea || !dropdown) return;

        const mailbox = selectAccount ? selectAccount.value : '';
        const items = await fetchSuggestions(mailbox);
        if (!items || items.length === 0) {
            dropdown.style.display = 'none';
            return;
        }

        let html = '<div class="suggestions-header">📋 Recent searches</div>';
        items.forEach((item, idx) => {
            const relTime = getRelativeTimeOrDate(item.last_searched_at);
            const newBadge = item.new_count > 0 ? `<span class="suggest-new-badge">+${item.new_count}</span>` : '';
            html += `
                <div class="suggestion-item" data-index="${idx}">
                    <div class="suggest-jd">${escapeHtml(item.jd)}</div>
                    <div class="suggest-meta">
                        <span>· ${relTime}</span>
                        <span>· ${item.results_count || 0} results</span>
                        ${newBadge}
                    </div>
                </div>
            `;
        });
        dropdown.innerHTML = html;
        dropdown.style.display = 'block';

        // Attach click handlers to items
        dropdown.querySelectorAll('.suggestion-item').forEach((row, i) => {
            row.addEventListener('click', () => {
                const item = items[i];
                textarea.value = item.jd;
                dropdown.style.display = 'none';
                hidePopupA();
                // Trigger search flow (with Feature B evaluation)
                triggerSearchFlow();
            });
        });
    }

    function hideSuggestions() {
        const dropdown = document.getElementById('search-suggestions-dropdown');
        if (dropdown) dropdown.style.display = 'none';
    }

    // ============================================================
    // FEATURE A: "You searched this before" Popup
    // ============================================================
    async function checkFeatureA() {
        const textarea = document.getElementById('job_query');
        const selectAccount = document.getElementById('account_email');
        if (!textarea) return;

        const jd = textarea.value.trim();
        const mailbox = selectAccount ? selectAccount.value : '';

        if (!jd || dismissedJDs.has(jd.toLowerCase())) {
            hidePopupA();
            return;
        }

        try {
            const res = await fetch(`/api/history/latest?mailbox=${encodeURIComponent(mailbox)}&jd=${encodeURIComponent(jd)}`);
            if (!res.ok) { hidePopupA(); return; }
            const data = await res.json();

            if (!data.found || !data.searched_at) {
                hidePopupA();
                return;
            }

            // Check if last search is > 24 hours old
            const lastDate = new Date(data.searched_at.replace('Z', '+00:00'));
            const now = new Date();
            const diffHours = (now - lastDate) / (1000 * 60 * 60);

            if (diffHours <= 24) {
                hidePopupA();
                return;
            }

            showPopupA(data, jd, mailbox);
        } catch (e) {
            hidePopupA();
        }
    }

    function showPopupA(data, jd, mailbox) {
        const popup = document.getElementById('searched-before-popup');
        if (!popup) return;

        const dateStr = formatDateShort(data.searched_at);
        const relTime = getRelativeTimeOrDate(data.searched_at);

        popup.innerHTML = `
            <div class="popup-a-card">
                <button type="button" class="popup-a-close" id="popup-a-close-btn">&times;</button>
                <div class="popup-a-title">🔔 You searched this before</div>
                <div class="popup-a-details">
                    <div>Mailbox: <strong>${escapeHtml(mailbox)}</strong></div>
                    <div>Last searched: <strong>${dateStr} (${relTime})</strong></div>
                    <div>Results last time: <strong>${data.results_count || 0} candidates</strong></div>
                </div>
                <div class="popup-a-actions">
                    <button type="button" class="btn-popup-a btn-search-again" id="popup-a-search-again">Search again</button>
                    <button type="button" class="btn-popup-a btn-show-last" id="popup-a-show-last">Show last results</button>
                </div>
            </div>
        `;
        popup.style.display = 'block';

        // Close button
        document.getElementById('popup-a-close-btn').addEventListener('click', () => {
            dismissedJDs.add(jd.toLowerCase());
            hidePopupA();
        });

        // Search again -> triggers Feature B evaluation then normal search
        document.getElementById('popup-a-search-again').addEventListener('click', () => {
            hidePopupA();
            triggerSearchFlow();
        });

        // Show last results -> Redirect to search history or show cached results
        document.getElementById('popup-a-show-last').addEventListener('click', () => {
            hidePopupA();
            if (data.search_id) {
                window.location.href = `/history?account_email=${encodeURIComponent(mailbox)}`;
            } else {
                triggerSearchFlow();
            }
        });
    }

    function hidePopupA() {
        const popup = document.getElementById('searched-before-popup');
        if (popup) popup.style.display = 'none';
    }

    // ============================================================
    // FEATURE B: "New candidates since last search" Popup / Modal
    // ============================================================
    async function triggerSearchFlow() {
        const form = document.getElementById('search-form');
        const textarea = document.getElementById('job_query');
        const selectAccount = document.getElementById('account_email');
        if (!form || !textarea) return;

        const jd = textarea.value.trim();
        const mailbox = selectAccount ? selectAccount.value : '';

        if (!jd) {
            form.submit();
            return;
        }

        try {
            const res = await fetch(`/api/history/delta?mailbox=${encodeURIComponent(mailbox)}&jd=${encodeURIComponent(jd)}`);
            if (!res.ok) { submitFormNormally(); return; }
            const data = await res.json();

            if (data.has_previous && data.new_count > 0) {
                showModalB(data, form, textarea);
            } else {
                submitFormNormally();
            }
        } catch (e) {
            submitFormNormally();
        }
    }

    function showModalB(data, form, textarea) {
        const overlay = document.getElementById('feature-b-modal-overlay');
        if (!overlay) { submitFormNormally(); return; }

        const dateStr = formatDateShort(data.last_searched_at);
        document.getElementById('feature-b-title').textContent = `${data.new_count} new matching resumes since your last search`;
        document.getElementById('feature-b-last-date').textContent = dateStr;
        document.getElementById('feature-b-new-count').textContent = data.new_count;
        document.getElementById('feature-b-seen-count').textContent = data.total_count - data.new_count;

        document.getElementById('feature-b-btn-new-num').textContent = data.new_count;
        document.getElementById('feature-b-btn-all-num').textContent = data.total_count;

        overlay.style.display = 'flex';

        const closeBtn = document.getElementById('feature-b-close');
        const cancelBtn = document.getElementById('feature-b-btn-cancel');
        const newOnlyBtn = document.getElementById('feature-b-btn-new');
        const searchAllBtn = document.getElementById('feature-b-btn-all');

        const closeModal = () => {
            overlay.style.display = 'none';
        };

        closeBtn.onclick = closeModal;
        cancelBtn.onclick = closeModal;

        newOnlyBtn.onclick = () => {
            closeModal();
            // Append after:YYYY/MM/DD to query if not already present
            if (data.after_date && !textarea.value.includes('after:')) {
                textarea.value = `${textarea.value.trim()} after:${data.after_date}`;
            }
            submitFormNormally();
        };

        searchAllBtn.onclick = () => {
            closeModal();
            submitFormNormally();
        };
    }

    function submitFormNormally() {
        const form = document.getElementById('search-form');
        if (form) {
            pendingFormSubmit = true;
            form.submit();
        }
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // ============================================================
    // INITIALIZATION & EVENT LISTENERS
    // ============================================================
    function setupApp() {
        initContainers();

        const textarea = document.getElementById('job_query');
        const form = document.getElementById('search-form');
        const selectAccount = document.getElementById('account_email');

        if (selectAccount) {
            fetchSuggestions(selectAccount.value);
            selectAccount.addEventListener('change', () => {
                fetchSuggestions(selectAccount.value);
            });
        }

        if (textarea) {
            textarea.addEventListener('focus', () => {
                showSuggestions();
            });
            textarea.addEventListener('click', () => {
                showSuggestions();
            });

            textarea.addEventListener('input', () => {
                hideSuggestions();
                clearTimeout(typingTimer);
                typingTimer = setTimeout(() => {
                    checkFeatureA();
                }, DEBOUNCE_DELAY);
            });
        }

        if (form) {
            form.addEventListener('submit', function(e) {
                if (pendingFormSubmit) return;
                e.preventDefault();
                hideSuggestions();
                hidePopupA();
                triggerSearchFlow();
            });
        }
    }

    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', setupApp);
    } else {
        setupApp();
    }

        // Dismiss popups on Escape or clicking outside
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                hideSuggestions();
                hidePopupA();
                const overlay = document.getElementById('feature-b-modal-overlay');
                if (overlay) overlay.style.display = 'none';
            }
        });

        document.addEventListener('click', (e) => {
            const dropdown = document.getElementById('search-suggestions-dropdown');
            const popup = document.getElementById('searched-before-popup');
            const modalCard = document.querySelector('.feature-b-modal-card');
            const overlay = document.getElementById('feature-b-modal-overlay');
            const textarea = document.getElementById('job_query');

            if (dropdown && !dropdown.contains(e.target) && e.target !== textarea) {
                hideSuggestions();
            }

            if (popup && !popup.contains(e.target) && e.target !== textarea) {
                // Keep popup open unless dismissed or clicked outside form area
                const formGroup = textarea ? textarea.closest('.form-group') : null;
                if (formGroup && !formGroup.contains(e.target)) {
                    hidePopupA();
                }
            }

            if (overlay && overlay.style.display === 'flex' && modalCard && !modalCard.contains(e.target)) {
                overlay.style.display = 'none';
            }
        });
    })();
