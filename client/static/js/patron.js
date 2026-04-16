/**
 * patron.js — History page Alpine.js component.
 *
 * Loads a patron's full transaction history from the API and provides
 * filtering by action type (checkout / return / renew).
 * Also supports searching patrons by first or last name.
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
        /** True while the card-lookup API request is in flight. */
        loading: false,
        /** Non-empty string when a load error has occurred (displayed inline). */
        errMsg: '',

        // ── Name search state ─────────────────────────────────────
        /** Current value of the name search input. */
        nameQuery: '',
        /** Results from GET /api/patrons/search. */
        nameResults: [],
        /** True while the name-search request is in flight. */
        nameSearching: false,
        /** True after at least one name search has been attempted. */
        nameSearched: false,

        /** True briefly when a non-digit is typed into the card field. */
        cardInvalid: false,
        _cardInvalidTimer: null,

        // ── Edit-patron state ────────────────────────────────────
        editing:    false,
        editSaving: false,
        editError:  '',
        editForm: {
            first_name:  '',
            last_name:   '',
            middle_name: '',
            birth_date:  '',
            email:       '',
            phone:       '',
        },

        // ── Archive-patron state ────────────────────────────────
        archiveActing: false,

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

        // ── Numeric input sanitiser ───────────────────────────────

        /**
         * Strip non-digit characters from the card input.
         * Flashes the invalid flag for 2.5s if any were stripped.
         *
         * @param {InputEvent} event - The input event.
         */
        sanitizeCard(event) {
            const raw = event.target.value;
            const clean = raw.replace(/\D/g, '').slice(0, 14);
            this.card = clean;
            if (event.target.value !== clean) event.target.value = clean;
            if (raw !== clean) {
                this.cardInvalid = true;
                clearTimeout(this._cardInvalidTimer);
                this._cardInvalidTimer = setTimeout(() => { this.cardInvalid = false; }, 2500);
            }
        },

        // ── Card-based data loading ───────────────────────────────

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
            this.nameResults = [];
            this.nameSearched = false;
            try {
                const r = await fetch(`/api/patrons/${encodeURIComponent(this.card.trim())}`);
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

        // ── Name search ───────────────────────────────────────────

        /**
         * Search for patrons by first or last name via GET /api/patrons/search.
         * Populates nameResults with the response.
         *
         * @returns {Promise<void>}
         */
        async searchByName() {
            const q = this.nameQuery.trim();
            if (!q) return;
            this.nameSearching = true;
            this.nameResults = [];
            this.nameSearched = false;
            this.data = null;
            this.errMsg = '';
            try {
                const r = await fetch(`/api/patrons/search?q=${encodeURIComponent(q)}`);
                const body = await r.json();
                if (!r.ok) {
                    this.errMsg = body.error || 'Search failed';
                    return;
                }
                this.nameResults = body;
                this.nameSearched = true;
            } catch (e) {
                this.errMsg = e.message;
            } finally {
                this.nameSearching = false;
            }
        },

        /**
         * Select a patron from the name-search results, load their history,
         * and clear the search results.
         *
         * @param {object} patron - Patron object from the search results.
         */
        selectPatron(patron) {
            this.card = patron.card_number;
            this.nameQuery = '';
            this.nameResults = [];
            this.nameSearched = false;
            this.load();
        },

        // ── Edit patron ───────────────────────────────────────────

        /** Pre-fill the edit form from the loaded patron and show the panel. */
        openEdit() {
            if (!this.data) return;
            const p = this.data.patron;
            this.editForm = {
                first_name:  p.first_name  || '',
                last_name:   p.last_name   || '',
                middle_name: p.middle_name || '',
                birth_date:  p.birth_date  || '',
                email:       p.email       || '',
                phone:       p.phone       || '',
            };
            this.editError = '';
            this.editing   = true;
        },

        cancelEdit() {
            this.editing   = false;
            this.editError = '';
        },

        async saveEdit() {
            if (!this.data) return;
            this.editSaving = true;
            this.editError  = '';
            try {
                const r = await fetch(`/api/patrons/${encodeURIComponent(this.data.patron.card_number)}`, {
                    method:  'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body:    JSON.stringify({
                        first_name:  this.editForm.first_name,
                        last_name:   this.editForm.last_name,
                        middle_name: this.editForm.middle_name,
                        birth_date:  this.editForm.birth_date || null,
                        email:       this.editForm.email,
                        phone:       this.editForm.phone,
                    }),
                });
                const data = await r.json();
                if (!r.ok) {
                    this.editError = data.error || 'Save failed';
                    return;
                }
                this.editing = false;
                // Refresh the patron summary so the header shows the new values
                await this.load();
            } catch (e) {
                this.editError = e.message;
            } finally {
                this.editSaving = false;
            }
        },

        /**
         * Soft-delete the patron account — requires zero active loans.
         * Prompts for confirmation first so it's not a single-click disaster.
         */
        async archivePatron() {
            if (!this.data) return;
            if (this.data.currently_out > 0) {
                this.editError = 'Return all items before archiving this patron.';
                return;
            }
            if (!confirm(
                `Archive ${this.data.patron.name}?\n\n` +
                `The account will be hidden from checkout but all history ` +
                `and loan records are preserved. You can reactivate it later.`
            )) return;

            this.archiveActing = true;
            this.editError     = '';
            try {
                const r = await fetch(
                    `/api/patrons/${encodeURIComponent(this.data.patron.card_number)}/archive`,
                    { method: 'POST' },
                );
                const data = await r.json();
                if (!r.ok) {
                    this.editError = data.error || 'Archive failed';
                    return;
                }
                await this.load();
            } catch (e) {
                this.editError = e.message;
            } finally {
                this.archiveActing = false;
            }
        },

        /** Undo an archive — brings the patron back into circulation. */
        async reactivatePatron() {
            if (!this.data) return;
            this.archiveActing = true;
            this.editError     = '';
            try {
                const r = await fetch(
                    `/api/patrons/${encodeURIComponent(this.data.patron.card_number)}/reactivate`,
                    { method: 'POST' },
                );
                const data = await r.json();
                if (!r.ok) {
                    this.editError = data.error || 'Reactivate failed';
                    return;
                }
                await this.load();
            } catch (e) {
                this.editError = e.message;
            } finally {
                this.archiveActing = false;
            }
        },

        // ── Return items ──────────────────────────────────────────

        /**
         * Return a single item from the active-items list.
         * Calls the return API and reloads the patron data.
         *
         * @param {string} barcode - The barcode of the item to return.
         * @returns {Promise<void>}
         */
        async returnItem(barcode) {
            try {
                const r = await fetch('/api/checkouts/return', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ barcode }),
                });
                const data = await r.json();
                if (!r.ok) {
                    this.errMsg = data.error || 'Return failed';
                    return;
                }
                await this.load();
            } catch (e) {
                this.errMsg = e.message;
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
