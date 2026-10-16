/**
 * LocalAdapter —— 方案 A：数据只存浏览器，零后端
 * ================================================
 * 优点：零成本、断网可用、零合规风险（数据根本没离开设备）
 * 缺点：换设备/清缓存数据就没了；你（开发者）看不到任何数据；无法多人共享
 */
import {
  CARD_STEPS, nextCardDue, addDays, todayStr,
  advanceCard, regressCard, resolveErrorOnce, makeId,
} from './contract.js';


/**
 * 安全深拷贝 —— 兼容不支持 structuredClone 的旧设备
 *
 * 为什么不用 structuredClone：
 *   它是 Chrome 98+ / Safari 15.4+（2022 年）才有的 API。
 *   本项目红线之一是「低配设备可用」，而大量旧安卓机 / 旧 WebView
 *   低于此版本 —— 直接调用会抛 ReferenceError，
 *   发生在构造函数里会导致**整个应用无法启动**。
 *
 * 降级方案：JSON 往返。对本项目的数据（纯 JSON：字符串/数字/布尔/数组/对象）
 * 完全等价，且 ES5 就支持。structuredClone 能处理的 Map/Set/Date 等
 * 本项目并不使用。
 */
function deepClone(obj) {
  if (typeof structuredClone === 'function') {
    try { return structuredClone(obj); } catch { /* 降级 */ }
  }
  return JSON.parse(JSON.stringify(obj));
}

const KEY = 'learnos.adapter.local.v1';

const EMPTY = { kids: {}, cards: {}, errors: {} };

export class LocalAdapter {
  constructor() {
    this.db = this._load();
  }

  _load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return deepClone(EMPTY);
      return Object.assign(deepClone(EMPTY), JSON.parse(raw));
    } catch { return deepClone(EMPTY); }
  }

  _save() {
    try { localStorage.setItem(KEY, JSON.stringify(this.db)); }
    catch { throw new Error('本地存储已满，请导出备份后清理'); }
  }

  // ---- 档案 ----
  async getKid(kidId) { return this.db.kids[kidId] || null; }

  async saveKid(profile) {
    const id = profile.id || makeId();
    const rec = { ...profile, id, createdAt: profile.createdAt || new Date().toISOString() };
    this.db.kids[id] = rec;
    this._save();
    return rec;
  }

  // ---- 知识卡 ----
  async listCards(kidId) {
    return Object.values(this.db.cards).filter(c => c.kidId === kidId);
  }

  async addCard(kidId, card) {
    const rec = {
      id: makeId(), kidId,
      front: card.front, back: card.back, subject: card.subject || '其他',
      step: 0, okCount: 0, due: todayStr(),
      createdAt: new Date().toISOString(),
    };
    this.db.cards[rec.id] = rec;
    this._save();
    return rec;
  }

  async gradeCard(kidId, cardId, remembered) {
    const c = this.db.cards[cardId];
    if (!c) throw new Error('卡片不存在');
    const next = remembered ? advanceCard(c) : regressCard(c);
    this.db.cards[cardId] = next;
    this._save();
    return next;
  }

  async deleteCard(kidId, cardId) {
    delete this.db.cards[cardId];
    this._save();
  }

  // ---- 错题 ----
  async listErrors(kidId) {
    return Object.values(this.db.errors).filter(e => e.kidId === kidId);
  }

  async addError(kidId, item) {
    const rec = {
      id: makeId(), kidId,
      question: item.question, thinking: item.thinking || '',
      gap: item.gap || '', type: item.type || '概念不懂',
      round: 0, due: addDays(3), archived: false,
      createdAt: new Date().toISOString(),
    };
    this.db.errors[rec.id] = rec;
    this._save();
    return rec;
  }

  async resolveError(kidId, errId) {
    const e = this.db.errors[errId];
    if (!e) throw new Error('错题不存在');
    const next = resolveErrorOnce(e);
    this.db.errors[errId] = next;
    this._save();
    return next;
  }

  async deleteError(kidId, errId) {
    delete this.db.errors[errId];
    this._save();
  }

  // ---- 合规：数据可携带 / 可删除 ----
  async exportAll(kidId) {
    return {
      exportedAt: new Date().toISOString(),
      kid: this.db.kids[kidId] || null,
      cards: await this.listCards(kidId),
      errors: await this.listErrors(kidId),
    };
  }

  async deleteAll(kidId) {
    Object.keys(this.db.cards).forEach(id => {
      if (this.db.cards[id].kidId === kidId) delete this.db.cards[id];
    });
    Object.keys(this.db.errors).forEach(id => {
      if (this.db.errors[id].kidId === kidId) delete this.db.errors[id];
    });
    delete this.db.kids[kidId];
    this._save();
  }

  /** 方案 A 特有：清空全部 */
  async wipe() { this.db = deepClone(EMPTY); this._save(); }
}
