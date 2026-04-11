/**
 * register.js — New-patron registration page Alpine.js component.
 *
 * Handles the full patron registration form:
 *   • Auto-fetches the next available card number from /api/patrons/next-card
 *     (or pre-fills from `?card=` when redirected from the checkout screen)
 *   • Validates required fields client-side before submitting
 *   • POSTs to /api/patrons/ and redirects to /?card=<card> on success
 *
 * Mounted via x-data="registerApp()" on the page root element in register.html.
 */

/**
 * Factory function that returns the Alpine.js component data and methods
 * for the patron registration screen.
 *
 * @returns {object} Alpine component object
 */
function registerApp() {
    return {
        // ── Form state ───────────────────────────────────────────
        /**
         * Registration form field values.
         * card_number uses a string to preserve leading zeros.
         */
        form: {
            card_number: '',
            first_name: '',
            last_name: '',
            middle_name: '',
            birth_date: '',
            email: '',
            phone: '',
        },

        /** True while the POST request is in flight. */
        submitting: false,

        /** Error message to show above the form, or empty string. */
        errorMsg: '',

        /** True when the card number was pre-filled from the URL (visual hint). */
        cardPreFilled: false,

        // ── Lifecycle ────────────────────────────────────────────

        /**
         * Alpine init hook.
         * If a `?card=` URL parameter is present (scanned at checkout), uses that number.
         * Otherwise fetches the next auto-generated card number from the server.
         * Focuses the last-name field once the card is resolved.
         */
        async init() {
            const params = new URLSearchParams(window.location.search);
            const card = params.get('card');
            if (card) {
                this.form.card_number = card;
                this.cardPreFilled = true;
            } else {
                try {
                    const r = await fetch('/api/patrons/next-card');
                    const data = await r.json();
                    this.form.card_number = data.card_number ?? '';
                } catch {
                    this.errorMsg = 'Could not generate a card number. Please refresh.';
                }
            }
            this.$nextTick(() => document.getElementById('reg-last')?.focus());
        },

        // ── Form submission ───────────────────────────────────────

        /**
         * Validate required fields and POST to /api/patrons/.
         * On success, redirects to the main checkout screen with the new card pre-loaded.
         *
         * @returns {Promise<void>}
         */
        async submit() {
            this.errorMsg = '';

            // Client-side required-field validation
            if (!this.form.last_name.trim()) {
                this.errorMsg = 'Last name is required.';
                return;
            }
            if (!this.form.first_name.trim()) {
                this.errorMsg = 'First name is required.';
                return;
            }
            if (!this.form.birth_date) {
                this.errorMsg = 'Date of birth is required.';
                return;
            }

            this.submitting = true;
            try {
                const body = {
                    card_number: this.form.card_number.trim(),
                    first_name:  this.form.first_name.trim(),
                    last_name:   this.form.last_name.trim(),
                    birth_date:  this.form.birth_date,
                };
                if (this.form.middle_name.trim()) body.middle_name = this.form.middle_name.trim();
                if (this.form.email.trim())       body.email       = this.form.email.trim();
                if (this.form.phone.trim())        body.phone       = this.form.phone.trim();

                const r = await fetch('/api/patrons/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await r.json();
                if (!r.ok) {
                    this.errorMsg = data.error || 'Registration failed. Please check your entries.';
                    return;
                }
                // Redirect to checkout screen; card is passed as query param to auto-load
                window.location.href = `/?card=${encodeURIComponent(data.card_number)}`;
            } catch (e) {
                this.errorMsg = e.message;
            } finally {
                this.submitting = false;
            }
        },
    };
}
