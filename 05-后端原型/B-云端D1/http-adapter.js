/**
 * HttpAdapter —— 方案 B：数据存云端（多家庭共享）
 * =================================================
 * 与 LocalAdapter 实现完全相同的接口，前端业务代码一行都不用改。
 *
 * 离线优先策略：网络失败时回落到本地缓存，保证断网仍能看/能改，
 * 恢复网络后由 syncPending() 补传。这是"教育平权"红线要求。
 */

const CACHE_KEY = 'learnos.adapter.http.cache.v1';
const PENDING_KEY = 'learnos.adapter.http.pending.v1';

export class HttpAdapter {
  /**
   * @param {string} baseUrl 后端地址，如 https://api.example.com
   * @param {string} token   会话令牌（合规：短时效、可撤销）
   */
  constructor(baseUrl, token = '') {
    this.base = baseUrl.replace(/\/$/, '');
    this.token = token;
    this.cache = this._read(CACHE_KEY, { cards: {}, errors: {}, kids: {} });
    this.pending = this._read(PENDING_KEY, []);
  }

  _read(k, dflt) {
    try { return Object.assign(structuredClone(dflt), JSON.parse(localStorage.getItem(k) || 'null') || {}); }
    catch { return structuredClone(dflt); }
  }
  _write(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }

  async _req(method, path, body) {
    const res = await fetch(this.base + path, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      throw new Error(`HTTP ${res.status}: ${txt.slice(0, 200)}`);
    }
    return res.status === 204 ? null : res.json();
  }

  /** 网络失败时排队，等恢复后补传 */
  _queue(op) { this.pending.push(op); this._write(PENDING_KEY, this.pending); }

  /** 补传离线期间的写入 */
  async syncPending() {
    if (!this.pending.length) return { synced: 0 };
    const left = [];
    let synced = 0;
    for (const op of this.pending) {
      try { await this._req(op.method, op.path, op.body); synced++; }
      catch { left.push(op); }
    }
    this.pending = left;
    this._write(PENDING_KEY, this.pending);
    return { synced, remaining: left.length };
  }

  // ---- 档案 ----
  async getKid(kidId) {
    try {
      const k = await this._req('GET', `/api/kids/${kidId}`);
      this.cache.kids[kidId] = k; this._write(CACHE_KEY, this.cache);
      return k;
    } catch { return this.cache.kids[kidId] || null; }
  }

  async saveKid(profile) {
    try {
      const k = await this._req('POST', '/api/kids', profile);
      this.cache.kids[k.id] = k; this._write(CACHE_KEY, this.cache);
      return k;
    } catch (e) {
      this._queue({ method: 'POST', path: '/api/kids', body: profile });
      throw e;
    }
  }

  // ---- 知识卡 ----
  async listCards(kidId) {
    try {
      const list = await this._req('GET', `/api/kids/${kidId}/cards`);
      this.cache.cards[kidId] = list; this._write(CACHE_KEY, this.cache);
      return list;
    } catch { return this.cache.cards[kidId] || []; }
  }

  async addCard(kidId, card) {
    try { return await this._req('POST', `/api/kids/${kidId}/cards`, card); }
    catch (e) { this._queue({ method: 'POST', path: `/api/kids/${kidId}/cards`, body: card }); throw e; }
  }

  async gradeCard(kidId, cardId, remembered) {
    return this._req('POST', `/api/kids/${kidId}/cards/${cardId}/grade`, { remembered });
  }

  async deleteCard(kidId, cardId) {
    return this._req('DELETE', `/api/kids/${kidId}/cards/${cardId}`);
  }

  // ---- 错题 ----
  async listErrors(kidId) {
    try {
      const list = await this._req('GET', `/api/kids/${kidId}/errors`);
      this.cache.errors[kidId] = list; this._write(CACHE_KEY, this.cache);
      return list;
    } catch { return this.cache.errors[kidId] || []; }
  }

  async addError(kidId, item) {
    try { return await this._req('POST', `/api/kids/${kidId}/errors`, item); }
    catch (e) { this._queue({ method: 'POST', path: `/api/kids/${kidId}/errors`, body: item }); throw e; }
  }

  async resolveError(kidId, errId) {
    return this._req('POST', `/api/kids/${kidId}/errors/${errId}/resolve`);
  }

  async deleteError(kidId, errId) {
    return this._req('DELETE', `/api/kids/${kidId}/errors/${errId}`);
  }

  // ---- 合规 ----
  async exportAll(kidId) {
    return this._req('GET', `/api/kids/${kidId}/export`);
  }

  async deleteAll(kidId) {
    const r = await this._req('DELETE', `/api/kids/${kidId}`);
    delete this.cache.kids[kidId];
    delete this.cache.cards[kidId];
    delete this.cache.errors[kidId];
    this._write(CACHE_KEY, this.cache);
    return r;
  }
}
