// Main checkout screen - Alpine.js component
function checkoutApp() {
    return {
        cardInput: '',
        itemInput: '',
        category: 'book',
        action: 'checkout',
        patron: null,
        message: '',
        error: false,

        init() {
            // Auto-focus barcode field after lookup
            this.$watch('patron', (p) => {
                if (p) setTimeout(() => document.querySelector('input[placeholder^="Scan barcode"]')?.focus(), 50);
            });
        },

        async lookupPatron() {
            this.message = '';
            const card = this.cardInput.trim();
            if (!card) return;
            try {
                const r = await fetch(`/api/patrons/${card}`);
                if (!r.ok) {
                    const err = await r.json();
                    // Patron not found - offer to register
                    if (r.status === 404) {
                        const name = prompt('New patron. Enter name (LAST, FIRST):');
                        if (!name) return;
                        const reg = await fetch('/api/patrons/', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ card_number: card, name }),
                        });
                        if (reg.ok) return this.lookupPatron();
                        this.flash((await reg.json()).error, true);
                        return;
                    }
                    this.flash(err.error, true);
                    return;
                }
                this.patron = await r.json();
            } catch (e) { this.flash(e.message, true); }
        },

        async submitAction() {
            if (!this.patron) return this.flash('Look up a patron first', true);
            if (!this.itemInput.trim()) return;

            const endpoint = {
                checkout: '/api/checkouts/',
                return: '/api/checkouts/return',
                renew: '/api/checkouts/renew',
            }[this.action];

            const body = {
                card_number: this.patron.patron.card_number,
                barcode: this.itemInput.trim(),
                category: this.category,
            };

            try {
                const r = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await r.json();
                if (!r.ok) return this.flash(data.error, true);
                this.flash(`✓ ${this.action} successful`, false);
                this.itemInput = '';
                await this.refreshPatron();
            } catch (e) { this.flash(e.message, true); }
        },

        async refreshPatron() {
            const r = await fetch(`/api/patrons/${this.patron.patron.card_number}`);
            if (r.ok) this.patron = await r.json();
        },

        printReceipt() {
            window.open(`/api/receipts/${this.patron.patron.card_number}`, '_blank');
        },

        flash(msg, isError) {
            this.message = msg;
            this.error = isError;
            setTimeout(() => (this.message = ''), 4000);
        },
    };
}