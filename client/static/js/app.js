/**
 * app.js — Main checkout screen Alpine.js component.
 *
 * Handles the full staff-facing checkout workflow:
 *   • Library-card lookup (404 → link to /register page instead of inline modal)
 *   • Checkout / Return / Renew actions via REST API
 *   • Custom loan period: preset (1/2/3 weeks) or custom number + unit (days/weeks/months)
 *   • Toast notification system (replaces alert / inline text)
 *   • Loading states on every async operation
 *
 * Mounted via x-data="checkoutApp()" on the page root element in index.html.
 */

/**
 * Factory function that returns the Alpine.js component data and methods
 * for the checkout screen.
 *
 * @returns {object} Alpine component object
 */
function checkoutApp() {
    return {
        // ── Core state ──────────────────────────────────────────
        /** Current value of the library-card / patron-search field. */
        cardInput: '',
        /** Current value of the item barcode / title search field. */
        itemInput: '',
        /** Active action tab: 'checkout' | 'return' | 'renew'. */
        action: 'checkout',
        /** Patron summary object returned by GET /api/patrons/:card, or null. */
        patron: null,
        /** Card number that was looked up but not found (triggers register link). */
        notFoundCard: '',

        /** Autofill dropdown state for the item barcode / title field. */
        itemResults:      [],
        itemSearching:    false,
        itemShowDropdown: false,
        itemHighlighted:  -1,
        _itemSearchTimer: null,

        /** Autofill dropdown state for the library-card / patron-name field. */
        cardResults:      [],
        cardSearching:    false,
        cardShowDropdown: false,
        cardHighlighted:  -1,
        _cardSearchTimer: null,

        // ── Loan period state ────────────────────────────────────
        /** Preset selection: '1' | '2' | '3' | 'custom'. */
        loanPreset: '2',
        /** Numeric value for custom loan period (1–9). */
        customLoanValue: 1,
        /** Unit for custom loan period: 'days' | 'weeks' | 'months'. */
        customLoanUnit: 'weeks',

        // ── Loading flags ────────────────────────────────────────
        /** True while the patron-lookup request is in flight. */
        cardLoading: false,
        /** True while a checkout / return / renew request is in flight. */
        actionLoading: false,
        /** True while the email-receipt request is in flight. */
        receiptEmailSending: false,

        // ── Toast notifications ──────────────────────────────────
        /**
         * Active toast objects: { id: number, msg: string, type: 'success'|'error'|'warning' }.
         * Each toast auto-removes itself after 4 seconds.
         */
        toasts: [],

        // ── Lifecycle ────────────────────────────────────────────

        /**
         * Alpine init hook.
         * Watches `patron` so the barcode field auto-focuses after a successful lookup.
         * Watches `action` so the barcode field auto-focuses when the tab changes.
         * Auto-loads patron if a `?card=` URL parameter is present (e.g. after registration).
         */
        init() {
            this.$watch('patron', (p) => {
                if (p) this.$nextTick(() => document.getElementById('barcode-input')?.focus());
            });
            this.$watch('action', () => {
                this.$nextTick(() => document.getElementById('barcode-input')?.focus());
            });
            // Auto-load from URL param (set by register page on success)
            const params = new URLSearchParams(window.location.search);
            const card = params.get('card');
            if (card) {
                this.cardInput = card;
                this.lookupPatron();
            }
        },

        // ── Input handlers ────────────────────────────────────────

        /**
         * Fires on every keystroke in the card / patron-search field.
         * Schedules a debounced search that matches patron names and
         * card-number prefixes.
         */
        onCardInput() {
            clearTimeout(this._cardSearchTimer);
            const q = this.cardInput.trim();
            if (!q) {
                this.cardResults      = [];
                this.cardShowDropdown = false;
                return;
            }
            this._cardSearchTimer = setTimeout(() => this._runCardSearch(), 180);
        },

        async _runCardSearch() {
            const q = this.cardInput.trim();
            if (!q) return;
            this.cardSearching = true;
            try {
                const r = await fetch(`/api/patrons/search?q=${encodeURIComponent(q)}`);
                const data = await r.json();
                if (r.ok && Array.isArray(data)) {
                    this.cardResults      = data;
                    this.cardShowDropdown = true;
                    this.cardHighlighted  = data.length > 0 ? 0 : -1;
                }
            } catch {
                this.cardResults = [];
            } finally {
                this.cardSearching = false;
            }
        },

        cardHighlightNext() {
            if (!this.cardShowDropdown || this.cardResults.length === 0) return;
            this.cardHighlighted = (this.cardHighlighted + 1) % this.cardResults.length;
        },

        cardHighlightPrev() {
            if (!this.cardShowDropdown || this.cardResults.length === 0) return;
            this.cardHighlighted =
                (this.cardHighlighted - 1 + this.cardResults.length) % this.cardResults.length;
        },

        selectCardResult(patron) {
            this.cardInput        = patron.card_number;
            this.cardResults      = [];
            this.cardShowDropdown = false;
            this.cardHighlighted  = -1;
            this.lookupPatron();
        },

        /**
         * Called on Enter in the card / patron-search field. If a dropdown
         * item is highlighted, selects it; otherwise runs a patron lookup
         * by the current value.
         */
        cardEnterKey() {
            if (this.cardShowDropdown && this.cardHighlighted >= 0 && this.cardResults[this.cardHighlighted]) {
                this.selectCardResult(this.cardResults[this.cardHighlighted]);
                return;
            }
            this.cardShowDropdown = false;
            this.lookupPatron();
        },

        /**
         * Fires on every keystroke in the item barcode / title field.
         * Schedules a debounced book search.
         */
        onItemInput() {
            this._scheduleItemSearch();
        },

        // ── Item autofill ─────────────────────────────────────────

        _scheduleItemSearch() {
            clearTimeout(this._itemSearchTimer);
            const q = this.itemInput.trim();
            if (!q) {
                this.itemResults      = [];
                this.itemShowDropdown = false;
                return;
            }
            this._itemSearchTimer = setTimeout(() => this._runItemSearch(), 180);
        },

        async _runItemSearch() {
            const q = this.itemInput.trim();
            if (!q) return;
            this.itemSearching = true;
            try {
                const r = await fetch(`/api/books/search?q=${encodeURIComponent(q)}&limit=10`);
                const data = await r.json();
                if (r.ok && Array.isArray(data)) {
                    this.itemResults      = data;
                    this.itemShowDropdown = true;
                    this.itemHighlighted  = data.length > 0 ? 0 : -1;
                }
            } catch {
                this.itemResults = [];
            } finally {
                this.itemSearching = false;
            }
        },

        itemHighlightNext() {
            if (!this.itemShowDropdown || this.itemResults.length === 0) return;
            this.itemHighlighted = (this.itemHighlighted + 1) % this.itemResults.length;
        },

        itemHighlightPrev() {
            if (!this.itemShowDropdown || this.itemResults.length === 0) return;
            this.itemHighlighted =
                (this.itemHighlighted - 1 + this.itemResults.length) % this.itemResults.length;
        },

        selectItem(book) {
            this.itemInput        = book.barcode;
            this.itemResults      = [];
            this.itemShowDropdown = false;
            this.itemHighlighted  = -1;
        },

        /**
         * Called on Enter in the item field.  If a dropdown item is highlighted,
         * selects it; otherwise submits the current action as before.
         */
        itemEnterKey() {
            if (this.itemShowDropdown && this.itemHighlighted >= 0 && this.itemResults[this.itemHighlighted]) {
                this.selectItem(this.itemResults[this.itemHighlighted]);
                return;
            }
            this.itemShowDropdown = false;
            this.submitAction();
        },

        // ── Patron lookup ─────────────────────────────────────────

        /**
         * Fetch patron summary by card number.
         * On 404 sets notFoundCard to display the registration link instead of alert().
         *
         * @returns {Promise<void>}
         */
        async lookupPatron() {
            const card = this.cardInput.trim();
            if (!card) return;
            this.cardLoading = true;
            this.notFoundCard = '';
            try {
                const r = await fetch(`/api/patrons/${encodeURIComponent(card)}`);
                if (!r.ok) {
                    const err = await r.json();
                    if (r.status === 404) {
                        this.notFoundCard = card;
                        this.patron = null;
                        return;
                    }
                    this.toast(err.error || 'Lookup failed', 'error');
                    return;
                }
                this.patron = await r.json();
            } catch (e) {
                this.toast(e.message, 'error');
            } finally {
                this.cardLoading = false;
            }
        },

        // ── Loan period ───────────────────────────────────────────

        /**
         * Compute the loan duration in days from the current preset/custom selection.
         * Preset values map directly to weeks (×7).
         * Custom value is clamped to 1–9 and multiplied by the selected unit factor.
         *
         * @returns {number} Loan period in days.
         */
        _computeLoanDays() {
            if (this.loanPreset !== 'custom') {
                return parseInt(this.loanPreset, 10) * 7;
            }
            const val = Math.max(1, Math.min(9, this.customLoanValue || 1));
            const factors = { days: 1, weeks: 7, months: 30 };
            return val * (factors[this.customLoanUnit] ?? 7);
        },

        // ── Checkout / return / renew ─────────────────────────────

        /**
         * Execute the current action (checkout, return, or renew) for the scanned barcode.
         * Refreshes the patron summary on success and clears the barcode field.
         *
         * @returns {Promise<void>}
         */
        async submitAction() {
            if (!this.patron) return this.toast('Look up a patron first', 'error');
            const barcode = this.itemInput.trim();
            if (!barcode) return this.toast('Enter or scan a barcode', 'warning');

            const endpoints = {
                checkout: '/api/checkouts/',
                return:   '/api/checkouts/return',
                renew:    '/api/checkouts/renew',
            };

            const body = {
                card_number: this.patron.patron.card_number,
                barcode,
            };
            if (this.action === 'checkout' || this.action === 'renew') {
                body.loan_days = this._computeLoanDays();
            }

            this.actionLoading = true;
            try {
                const r = await fetch(endpoints[this.action], {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await r.json();
                if (!r.ok) {
                    this.toast(data.error || 'Action failed', 'error');
                    return;
                }
                const labels = { checkout: 'Checked out', return: 'Returned', renew: 'Renewed' };
                this.toast(`${labels[this.action]}: ${barcode}`, 'success');
                this.itemInput = '';
                await this.refreshPatron();
            } catch (e) {
                this.toast(e.message, 'error');
            } finally {
                this.actionLoading = false;
            }
        },

        /**
         * Re-fetch the current patron's summary to refresh counts and active-items table.
         *
         * @returns {Promise<void>}
         */
        async refreshPatron() {
            try {
                const r = await fetch(`/api/patrons/${encodeURIComponent(this.patron.patron.card_number)}`);
                if (r.ok) this.patron = await r.json();
            } catch (_) { /* silent — stale UI is acceptable */ }
        },

        /**
         * Open the PDF receipt for the current patron in a new browser tab.
         */
        printReceipt() {
            window.open(`/api/receipts/${this.patron.patron.card_number}`, '_blank');
        },

        /**
         * POST to /api/receipts/<card>/email which builds the receipt PDF
         * and sends it as an attachment to the patron's email on file.
         */
        async emailReceipt() {
            if (!this.patron) return;
            const card = this.patron.patron.card_number;
            if (!this.patron.patron.email) {
                this.toast('Patron has no email address on file', 'warning');
                return;
            }
            this.receiptEmailSending = true;
            try {
                const r = await fetch(`/api/receipts/${encodeURIComponent(card)}/email`, {
                    method: 'POST',
                });
                const data = await r.json();
                if (!r.ok) {
                    this.toast(data.error || 'Email failed', 'error');
                    return;
                }
                this.toast(`Receipt emailed to ${data.to}`, 'success');
            } catch (e) {
                this.toast(e.message, 'error');
            } finally {
                this.receiptEmailSending = false;
            }
        },

        /**
         * Return a single item directly from the active-items table.
         * Calls the return API and refreshes the patron summary.
         *
         * @param {string} barcode - The barcode of the item to return.
         * @returns {Promise<void>}
         */
        async returnSingleItem(barcode) {
            try {
                const r = await fetch('/api/checkouts/return', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ barcode }),
                });
                const data = await r.json();
                if (!r.ok) {
                    this.toast(data.error || 'Return failed', 'error');
                    return;
                }
                this.toast(`Returned: ${barcode}`, 'success');
                await this.refreshPatron();
            } catch (e) {
                this.toast(e.message, 'error');
            }
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
         * Map an item category string to the Tailwind badge colour classes.
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

        /**
         * Push a toast notification and schedule its removal after 4 seconds.
         *
         * @param {string} msg  - The message to display.
         * @param {'success'|'error'|'warning'} [type='success'] - Toast severity.
         */
        toast(msg, type = 'success') {
            const id = Date.now() + Math.random();
            this.toasts.push({ id, msg, type });
            setTimeout(() => {
                this.toasts = this.toasts.filter((t) => t.id !== id);
            }, 4000);
        },
    };
}
