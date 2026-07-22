const API_BASE = 'http://localhost:5000/api';

const Utils = {
    async post(url, data) {
        const res = await fetch(`${API_BASE}${url}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    },

    async get(url) {
        const res = await fetch(`${API_BASE}${url}`);
        return await res.json();
    },

    async patch(url, data) {
        const res = await fetch(`${API_BASE}${url}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    },

    saveUser(user) {
        localStorage.setItem('ptp_user', JSON.stringify(user));
    },

    getUser() {
        const user = localStorage.getItem('ptp_user');
        return user ? JSON.parse(user) : null;
    },

    logout() {
        localStorage.removeItem('ptp_user');
        window.location.href = '../login.html';
    },

    logoutFromRoot() {
        localStorage.removeItem('ptp_user');
        window.location.href = 'login.html';
    },

    saveAdmin(admin) {
        localStorage.setItem('ptp_admin', JSON.stringify(admin));
    },

    getAdmin() {
        const admin = localStorage.getItem('ptp_admin');
        return admin ? JSON.parse(admin) : null;
    },

    logoutAdmin() {
        localStorage.removeItem('ptp_admin');
        window.location.href = '/admin/login.html';
    }
};

window.Utils = Utils;
