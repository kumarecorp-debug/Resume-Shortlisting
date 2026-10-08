// search.js - Frontend progress polling and search state management

(function() {
    console.log("[search.js] Initializing async search module...");

    window.initSearchProgress = function(searchId, containerId) {
        if (!searchId) return;

        let elapsed = 0;
        let isWaiting = false;

        const pollInterval = setInterval(async () => {
            try {
                const res = await fetch(`/api/search/status?search_id=${searchId}`);
                if (!res.ok) return;

                const data = await res.json();
                console.log("[search.js] Status update:", data);

                const status = data.status;
                const candidates = data.candidates || [];
                const reason = data.reason || "";

                if (status === 'timeout' || data.error) {
                    const msgElem = document.getElementById('search-message');
                    if (msgElem) msgElem.textContent = "Search is taking longer than expected. Please wait...";
                } else if (status === 'done') {
                    clearInterval(pollInterval);
                    if (candidates.length === 0) {
                        const msgElem = document.getElementById('search-message');
                        if (msgElem) {
                            msgElem.textContent = reason || "No candidates found. Try broader search terms.";
                            msgElem.style.display = 'block';
                        }
                    } else {
                        // Redirect to results view if not already there
                        if (window.location.pathname.includes('/search-progress/')) {
                            window.location.href = `/search-results/${searchId}`;
                        }
                    }
                }
            } catch (err) {
                console.error("[search.js] Status poll error:", err);
            }
        }, 2000);
    };
})();
