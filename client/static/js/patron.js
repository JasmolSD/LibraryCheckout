/**
 * patron.js — History page Alpine.js component.
 *
 * Loads a patron's full transaction history from the API and provides
 * filtering by action type (checkout / return / renew).
 *
 * Mounted via x-data="historyApp()" on the page root element in history.html.
 * Auto-loads if a `?card=` query-string parameter is present in the URL
 * (set by the "View full history →" link on the checkout screen).
 */

/**
 * Factory function that returns the Alpine.js component data and methods
 * for the patron history screen.
 *
 * @returns {object} Alpine component object
 */
function historyApp() {
    return {
        // ── State ────────────────────────────────────────────────
        /** Current value of the card-number input field. */
        card: '',
        /**
         * Patron summary returned by GET /api/patrons/:card, or null.
         * Shape: { patron, total_checkouts, currently_out, late_count, account_age_days, history[] }
         */
        data: null,
        /** Active filter: 'all' | 'checkout' | 'return' | 'renew'. */
        filter: 'all',
        /** True while the API request is in flight. */
        loading: false,
        /** Non-empty string when a load error has occurred (displayed inline). */
        errMsg: '',

        // ── Lifecycle ────────────────────────────────────────────

        /**
         * Alpine init hook.
         * If the URL contains a `card` query parameter, pre-fills the input
         * and triggers an automatic load (used when navigating from the checkout screen).
         */
        init() {
            const params = new URLSearchParams(window.location.search);
            const c = params.get('card');
            if (c) {
                this.card = c;
                this.load();
            }
        },

        // ── Data loading ──────────────────────────────────────────

        /**
         * Fetch patron summary and transaction history from the API.
         * Clears any previous error and resets the filter to 'all' on success.
         *
         * @returns {Promise<void>}
         */
        async load() {
            if (!this.card.trim()) return;
            this.loading = true;
            this.errMsg = '';
            this.data = null;
            try {
                const r = await fetch(`/api/patrons/${this.card.trim()}`);
                if (!r.ok) {
                    const e = await r.json();
                    this.errMsg = e.error || 'Patron not found';
                    return;
                }
                this.data = await r.json();
                this.filter = 'all';
            } catch (e) {
                this.errMsg = e.message;
            } finally {
                this.loading = false;
            }
        },

        // ── Filtering ─────────────────────────────────────────────

        /**
         * Return the subset of history rows matching the current filter tab.
         *
         * @returns {object[]} Filtered array of checkout/return/renew records.
         */
        filteredHistory() {
            if (!this.data) return [];
            if (this.filter === 'all') return this.data.history;
            return this.data.history.filter((r) => r.action === this.filter);
        },

        /**
         * Return the count of history rows that match a given filter value.
         * Used to display counts in filter tab labels.
         *
         * @param {string} f - Filter value: 'all' | 'checkout' | 'return' | 'renew'.
         * @returns {number} Number of matching rows.
         */
        countFor(f) {
            if (!this.data) return 0;
            if (f === 'all') return this.data.history.length;
            return this.data.history.filter((r) => r.action === f).length;
        },

        // ── Helpers ───────────────────────────────────────────────

        /**
         * Derive two-letter initials from a patron name in "LAST, FIRST" or "First Last" format.
         *
         * @param {string} name - Raw patron name.
         * @returns {string} Up to two uppercase initials, e.g. "DJ".
         */
        initials(name) {
            if (!name) return '?';
            const words = name.replace(',', '').trim().split(/\s+/).filter(Boolean);
            if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
            return (words[0]?.[0] ?? '?').toUpperCase();
        },

        /**
         * Map an action string to Tailwind badge colour classes.
         *
         * @param {string} action - 'checkout' | 'return' | 'renew'.
         * @returns {string} Tailwind class string for the badge element.
         */
        badgeClass(action) {
            const map = {
                checkout: 'bg-emerald-100 text-emerald-700',
                return:   'bg-blue-100    text-blue-700',
                renew:    'bg-amber-100   text-amber-700',
            };
            return map[action] ?? 'bg-slate-100 text-slate-600';
        },

        /**
         * Map an item category string to Tailwind badge colour classes.
         *
         * @param {string} cat - Category value from the API (e.g. "book", "dvd").
         * @returns {string} Tailwind class string for the badge element.
         */
        categoryBadge(cat) {
            const map = {
                book:      'bg-indigo-100 text-indigo-700',
                dvd:       'bg-purple-100 text-purple-700',
                audiobook: 'bg-teal-100   text-teal-700',
                magazine:  'bg-orange-100 text-orange-700',
                ebook:     'bg-sky-100    text-sky-700',
                other:     'bg-slate-100  text-slate-600',
            };
            return map[cat] ?? 'bg-slate-100 text-slate-600';
        },
    };
}
