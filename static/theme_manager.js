(function() {
    async function applyTheme() {
        const username = localStorage.getItem('quiz_username') || localStorage.getItem('quiz_admin_username');
        let theme = null;

        // Try to fetch from server first if logged in
        if (username) {
            try {
                const res = await fetch(`/api/user/preferences/get?username=${username}`);
                const data = await res.json();
                if (data.success && data.theme) {
                    theme = data.theme;
                    // Also update local storage for speed on next page load
                    localStorage.setItem('examq_theme', JSON.stringify(theme));
                }
            } catch (e) { console.error("Theme sync failed", e); }
        }

        // Fallback to local storage
        if (!theme) {
            const localTheme = localStorage.getItem('examq_theme');
            if (localTheme) theme = JSON.parse(localTheme);
        }

        if (!theme) return;

        const { primary, secondary } = theme;
        const root = document.documentElement;
        
        root.style.setProperty('--primary-color', primary);
        root.style.setProperty('--secondary-color', secondary);
        
        const gradient = `linear-gradient(135deg, ${primary} 0%, ${secondary} 100%)`;
        root.style.setProperty('--main-gradient', gradient);
    }

    // Run immediately
    applyTheme();

    // Export for later use
    window.ThemeManager = {
        apply: applyTheme,
        save: async (primary, secondary) => {
            const theme = { primary, secondary };
            localStorage.setItem('examq_theme', JSON.stringify(theme));
            applyTheme();

            const username = localStorage.getItem('quiz_username') || localStorage.getItem('quiz_admin_username');
            if (username) {
                try {
                    await fetch('/api/user/preferences/save', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ username, theme })
                    });
                } catch (e) { console.error("Failed to save theme to server", e); }
            }
        },
        reset: async () => {
            localStorage.removeItem('examq_theme');
            const username = localStorage.getItem('quiz_username') || localStorage.getItem('quiz_admin_username');
            if (username) {
                try {
                    await fetch('/api/user/preferences/save', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ username, theme: null })
                    });
                } catch (e) {}
            }
            location.reload();
        }
    };
})();
