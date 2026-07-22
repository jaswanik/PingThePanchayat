/**
 * admin-utils.js — Utilities for Admin portal only
 * Admin access is via hidden route: /admin/login.html
 */

// Define API_BASE globally on window if not already defined
window.API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') && window.location.port === '8000'
    ? 'http://localhost:5000/api'
    : '/api';


// Define requireAdmin helper globally
window.requireAdmin = function() {
    if (typeof Utils !== 'undefined' && typeof Utils.getAdmin === 'function') {
        if (!Utils.getAdmin()) {
            window.location.href = 'login.html';
        }
    } else {
        const admin = localStorage.getItem('ptp_admin');
        if (!admin) {
            window.location.href = 'login.html';
        }
    }
};

// Initialize or extend the global Utils object
window.Utils = window.Utils || {};

// Add or override utility functions
if (!window.Utils.post) {
    window.Utils.post = async function(url, data) {
        try {
            const res = await fetch(`${window.API_BASE}${url}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            return await res.json();
        } catch (err) {
            console.error(`Utils.post failed for ${url}:`, err);
            throw err;
        }
    };
}

if (!window.Utils.get) {
    window.Utils.get = async function(url) {
        try {
            const res = await fetch(`${window.API_BASE}${url}`);
            return await res.json();
        } catch (err) {
            console.error(`Utils.get failed for ${url}:`, err);
            throw err;
        }
    };
}

if (!window.Utils.patch) {
    window.Utils.patch = async function(url, data) {
        try {
            const res = await fetch(`${window.API_BASE}${url}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            return await res.json();
        } catch (err) {
            console.error(`Utils.patch failed for ${url}:`, err);
            throw err;
        }
    };
}

window.Utils.saveAdmin = function(admin) {
    localStorage.setItem('ptp_admin', JSON.stringify(admin));
};

window.Utils.getAdmin = function() {
    const admin = localStorage.getItem('ptp_admin');
    return admin ? JSON.parse(admin) : null;
};

window.Utils.logout = function() {
    localStorage.removeItem('ptp_admin');
    window.location.href = 'login.html';  // Redirect to admin/login.html
};

window.Utils.saveUser = function(user) {
    localStorage.setItem('ptp_user', JSON.stringify(user));
};

window.Utils.getUser = function() {
    const user = localStorage.getItem('ptp_user');
    return user ? JSON.parse(user) : null;
};

