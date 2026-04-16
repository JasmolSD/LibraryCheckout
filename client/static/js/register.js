/**
 * register.js — Registration page Alpine.js component.
 *
 * Hosts two tabs:
 *   • Patron — auto-generates a card number and registers a new patron
 *   • Book   — scans an ISBN (auto-fills via Google Books) and adds the
 *              item to the catalog with a quantity
 *
 * The Book tab is the canonical place to add new items; the /catalog
 * page is for searching and managing items that already exist.
 *
 * Mounted via x-data="registerApp()" on the page root element in register.html.
 *
 * @returns {object} Alpine component object
 */
function registerApp() {
    return {
        // ── Tab state ───────────────────────────────────────────
        /** Active tab: 'patron' | 'book'. */
        tab: 'patron',

        // ── Patron state ────────────────────────────────────────
        patronForm: {
            card_number: '',
            first_name:  '',
            last_name:   '',
            middle_name: '',
            birth_date:  '',
            email:       '',
            phone:       '',
        },
        patronSubmitting: false,
        patronError:      '',
        cardPreFilled:    false,
        /** Set after a successful patron registration: { card_number, name, email }. */
        patronRegistered: null,
        emailSending:     false,
        emailStatus:      '',  // '' | 'sent' | 'error'
        emailMessage:     '',

        // ── Book state ──────────────────────────────────────────
        bookForm: {
            barcode:  '',
            title:    '',
            author:   '',
            category: 'book',
            quantity: 1,
        },
        bookSubmitting:     false,
        bookLookingUp:      false,
        bookLookupStatus:   '',
        bookError:          '',
        bookSuccess:        '',
        bookLastLookedUp:   '',
        bookBarcodeInvalid: false,
        _bookInvalidTimer:  null,

        // ── Lifecycle ────────────────────────────────────────────

        async init() {
            const params = new URLSearchParams(window.location.search);
            // ?tab=book opens straight to the book form
            if (params.get('tab') === 'book') this.tab = 'book';

            const card = params.get('card');
            if (card) {
                this.patronForm.card_number = card;
                this.cardPreFilled = true;
            } else {
                try {
                    const r = await fetch('/api/patrons/next-card');
                    const data = await r.json();
                    this.patronForm.card_number = data.card_number ?? '';
                } catch {
                    this.patronError = 'Could not generate a card number. Please refresh.';
                }
            }
            this.$nextTick(() => {
                if (this.tab === 'patron') {
                    document.getElementById('reg-last')?.focus();
                } else {
                    document.getElementById('isbn')?.focus();
                }
            });
        },

        // ── Patron submission ────────────────────────────────────

        async submitPatron() {
            this.patronError = '';
            if (!this.patronForm.last_name.trim()) {
                this.patronError = 'Last name is required.';
                return;
            }
            if (!this.patronForm.first_name.trim()) {
                this.patronError = 'First name is required.';
                return;
            }
            if (!this.patronForm.birth_date) {
                this.patronError = 'Date of birth is required.';
                return;
            }

            this.patronSubmitting = true;
            try {
                const body = {
                    card_number: this.patronForm.card_number.trim(),
                    first_name:  this.patronForm.first_name.trim(),
                    last_name:   this.patronForm.last_name.trim(),
                    birth_date:  this.patronForm.birth_date,
                };
                if (this.patronForm.middle_name.trim()) body.middle_name = this.patronForm.middle_name.trim();
                if (this.patronForm.email.trim())       body.email       = this.patronForm.email.trim();
                if (this.patronForm.phone.trim())       body.phone       = this.patronForm.phone.trim();

                const r = await fetch('/api/patrons/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await r.json();
                if (!r.ok) {
                    this.patronError = data.error || 'Registration failed. Please check your entries.';
                    return;
                }
                // Show the "what next?" panel instead of immediately redirecting,
                // so the librarian has a chance to print the patron's card.
                this.patronRegistered = {
                    card_number: data.card_number,
                    name:        data.name,
                    email:       data.email || '',
                };
                this.emailStatus  = '';
                this.emailMessage = '';
            } catch (e) {
                this.patronError = e.message;
            } finally {
                this.patronSubmitting = false;
            }
        },

        /** Open the printable patron card PDF in a new tab. */
        printPatronCard() {
            if (!this.patronRegistered) return;
            window.open(
                `/api/patrons/${encodeURIComponent(this.patronRegistered.card_number)}/card-pdf`,
                '_blank',
            );
        },

        /** Email the patron card PDF to the patron's address on file. */
        async emailPatronCard() {
            if (!this.patronRegistered) return;
            this.emailSending = true;
            this.emailStatus  = '';
            this.emailMessage = '';
            try {
                const r = await fetch(
                    `/api/patrons/${encodeURIComponent(this.patronRegistered.card_number)}/card-email`,
                    { method: 'POST' },
                );
                const data = await r.json();
                if (!r.ok) {
                    this.emailStatus  = 'error';
                    this.emailMessage = data.error || 'Could not send email.';
                    return;
                }
                this.emailStatus  = 'sent';
                this.emailMessage = `Sent to ${data.to}`;
            } catch (e) {
                this.emailStatus  = 'error';
                this.emailMessage = e.message;
            } finally {
                this.emailSending = false;
            }
        },

        /** Finish the registration flow — redirect to checkout with the card pre-loaded. */
        finishPatronRegistration() {
            if (!this.patronRegistered) return;
            window.location.href = `/?card=${encodeURIComponent(this.patronRegistered.card_number)}`;
        },

        // ── Book: numeric sanitiser + ISBN auto-fill ─────────────

        sanitizeBarcode(event) {
            const raw = event.target.value;
            const clean = raw.replace(/\D/g, '').slice(0, 14);
            this.bookForm.barcode = clean;
            if (event.target.value !== clean) event.target.value = clean;
            if (raw !== clean) {
                this.bookBarcodeInvalid = true;
                clearTimeout(this._bookInvalidTimer);
                this._bookInvalidTimer = setTimeout(() => { this.bookBarcodeInvalid = false; }, 2500);
            }
        },

        async onIsbnChange() {
            const isbn = this.bookForm.barcode.trim();
            if (!isbn || isbn === this.bookLastLookedUp) return;
            if (!/^\d{10}$|^\d{13}$/.test(isbn)) return;

            this.bookLastLookedUp = isbn;
            this.bookLookingUp    = true;
            this.bookLookupStatus = '';
            try {
                const r    = await fetch(`/api/books/lookup?isbn=${encodeURIComponent(isbn)}`);
                const data = await r.json();
                if (data.found) {
                    if (data.title)    this.bookForm.title    = data.title;
                    if (data.author)   this.bookForm.author   = data.author;
                    if (data.category) this.bookForm.category = data.category;
                    this.bookLookupStatus = 'found';
                } else if (data.error === 'metadata service unavailable') {
                    this.bookLookupStatus = 'unavailable';
                } else {
                    this.bookLookupStatus = 'not_found';
                }
            } catch {
                this.bookLookupStatus = 'unavailable';
            } finally {
                this.bookLookingUp = false;
            }
        },

        // ── Book submission ──────────────────────────────────────

        async submitBook() {
            this.bookError   = '';
            this.bookSuccess = '';
            if (!this.bookForm.barcode.trim()) {
                this.bookError = 'ISBN or barcode is required.';
                return;
            }
            this.bookSubmitting = true;
            try {
                const qty = Math.max(1, parseInt(this.bookForm.quantity, 10) || 1);
                const r = await fetch('/api/books/', {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body:    JSON.stringify({
                        barcode:  this.bookForm.barcode.trim(),
                        title:    this.bookForm.title.trim()    || null,
                        author:   this.bookForm.author.trim()   || null,
                        category: this.bookForm.category,
                        quantity: qty,
                    }),
                });
                const data = await r.json();
                if (!r.ok) {
                    this.bookError = data.error || 'Could not add the item.';
                    return;
                }
                const label = data.title ? `"${data.title}"` : `barcode ${data.barcode}`;
                const copyNote = qty > 1 ? ` (${qty} copies)` : '';
                this.bookSuccess = `Added ${label} to the catalog${copyNote}.`;
            } catch (e) {
                this.bookError = e.message;
            } finally {
                this.bookSubmitting = false;
            }
        },

        resetBook() {
            this.bookForm         = { barcode: '', title: '', author: '', category: 'book', quantity: 1 };
            this.bookSuccess      = '';
            this.bookError        = '';
            this.bookLookupStatus = '';
            this.bookLastLookedUp = '';
            this.$nextTick(() => document.getElementById('isbn')?.focus());
        },
    };
}
