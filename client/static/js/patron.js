// History page - Alpine.js component
function historyApp() {
    return {
        card: '',
        data: null,

        init() {
            // Auto-load if ?card= query param is present
            const params = new URLSearchParams(window.location.search);
            const c = params.get('card');
            if (c) {
                this.card = c;
                this.load();
            }
        },

        async load() {
            if (!this.card.trim()) return;
            try {
                const r = await fetch(`/api/patrons/${this.card.trim()}`);
                if (!r.ok) {
                    const e = await r.json();
                    alert(e.error || 'Patron not found');
                    return;
                }
                this.data = await r.json();
            } catch (e) {
                alert(e.message);
            }
        },

        badgeClass(action) {
            return {
                checkout: 'bg-emerald-100 text-emerald-700',
                return: 'bg-blue-100 text-blue-700',
                renew: 'bg-amber-100 text-amber-700',
            }[action] || 'bg-slate-100';
        },
    };
}