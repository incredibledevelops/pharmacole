/* Offline POS helper — include in cashier/pos.html */
(function () {
  'use strict';

  const DB_NAME = 'pharmacole-offline';
  const DB_VER = 1;
  const STORE = 'queued_sales';

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VER);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'client_uuid' });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function enqueue(sale) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(sale);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async function all() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  async function remove(uuid) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(uuid);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  function uuid() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  async function syncQueued(token, apiBase) {
    const queued = await all();
    if (!queued.length) return { synced: 0 };

    const results = await fetch(`${apiBase}/sales/sync`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ sales: queued }),
    }).then(r => r.json());

    let synced = 0;
    for (const r of results.results || []) {
      if (r.ok) { await remove(r.client_uuid); synced++; }
    }
    return { synced, pending: queued.length - synced };
  }

  // Public API
  window.OfflinePOS = {
    uuid,
    enqueue,
    all,
    remove,
    syncQueued,
    isOnline: () => navigator.onLine,
  };

  // Auto-sync on reconnect
  window.addEventListener('online', async () => {
    const token = localStorage.getItem('pharmacole_api_token');
    const apiBase = localStorage.getItem('pharmacole_api_base') || '/api/v1';
    if (!token) return;
    try {
      const r = await syncQueued(token, apiBase);
      if (r.synced) console.log('[OfflinePOS] Synced', r.synced, 'sales');
    } catch (e) { console.warn('[OfflinePOS] sync failed', e); }
  });
})();