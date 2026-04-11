/**
 * app.js — Main checkout screen Alpine.js component.
 *
 * Handles the full staff-facing checkout workflow:
 *   • Library-card lookup with automatic new-patron registration modal
 *   • Checkout / Return / Renew actions via REST API
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
        /** Current value of the library-card input field. */
        cardInput: '',
        /** Current value of the barcode input field. */
        itemInput: '',
        /** Selected item category for checkout actions. */
        category: 'book',
        /** Active action tab: 'checkout' | 'return' | 'renew'. */
        action: 'checkout',
        /** Patron summary object returned by GET /api/patrons/:card, or null. */
        patron: null,

        // ── Loading flags ────────────────────────────────────────
        /** True while the patron-lookup request is in flight. */
        cardLoading: false,
        /** True while a checkout / return / renew request is in flight. */
        actionLoading: false,
        /** True while the patron-registration POST is in flight. */
        registerLoading: false,

        // ── Toast notifications ──────────────────────────────────
        /**
         * Active toast objects: { id: number, msg: string, type: 'success'|'error'|'warning' }.
         * Each toast auto-removes itself after 4 seconds.
         */
        toasts: [],

        // ── Registration modal ───────────────────────────────────
        /** Whether the new-patron registration modal is visible. */
        showModal: false,
        /** Card number that triggered the "patron not found" path. */
        pendingCard: '',
        /** Name field value inside the registration modal. */
        registerName: '',
        /** Email field value inside the registration modal (optional). */
        registerEmail: '',

        // ── Lifecycle ────────────────────────────────────────────

        /**
         * Alpine init hook.
         * Watches `patron` so the barcode field auto-focuses after a successful lookup.
         * Watches `action` so the barcode field auto-focuses when the tab changes.
         */
        init() {
            this.$watch('patron', (p) => {
                if (p) this.$nextTick(() => document.getElementById('barcode-input')?.focus());
            });
            this.$watch('action', () => {
                this.$nextTick(() => document.getElementById('barcode-input')?.focus());
            });
        },

        // ── Patron lookup ─────────────────────────────────────────

        /**
         * Fetch patron summary by card number.
         * On 404 opens the registration modal instead of calling prompt().
         *
         * @returns {Promise<void>}
         */
        async lookupPatron() {
            const card = this.cardInput.trim();
            if (!card) return;
            this.cardLoading = true;
            try {
                const r = await fetch(`/api/patrons/${card}`);
                if (!r.ok) {
                    const err = await r.json();
                    if (r.status === 404) {
                        this.openRegisterModal(card);
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

        // ── Registration modal ────────────────────────────────────

        /**
         * Open the new-patron registration modal for the given card number.
         * Focuses the name field after the modal becomes visible.
         *
         * @param {string} card - The unrecognised card number.
         */
        openRegisterModal(card) {
            this.pendingCard = card;
            this.registerName = '';
            this.registerEmail = '';
            this.showModal = true;
            this.$nextTick(() => document.getElementById('register-name')?.focus());
        },

        /**
         * Submit the new-patron registration form.
         * On success the modal closes and the patron is loaded automatically.
         *
         * @returns {Promise<void>}
         */
        async confirmRegister() {
            if (!this.registerName.trim()) return;
            this.registerLoading = true;
            try {
                const r = await fetch('/api/patrons/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        card_number: this.pendingCard,
                        name: this.registerName.trim(),
                        email: this.registerEmail.trim() || null,
                    }),
                });
                const data = await r.json();
                if (!r.ok) {
                    this.toast(data.error || 'Registration failed', 'error');
                    return;
                }
                this.showModal = false;
                this.cardInput = this.pendingCard;
                this.toast(`Registered ${data.name}`, 'success');
                await this.lookupPatron();
            } catch (e) {
                this.toast(e.message, 'error');
            } finally {
                this.registerLoading = false;
            }
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
                category: this.category,
            };
            if (this.action === 'renew') body.weeks = 3;

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
                const r = await fetch(`/api/patrons/${this.patron.patron.card_number}`);
                if (r.ok) this.patron = await r.json();
            } catch (_) { /* silent — stale UI is acceptable */ }
        },

        /**
         * Open the PDF receipt for the current patron in a new browser tab.
         */
        printReceipt() {
            window.open(`/api/receipts/${this.patron.patron.card_number}`, '_blank');
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
