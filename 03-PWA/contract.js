/**
 * 数据层契约（Data Layer Contract）
 * ====================================
 * 这是本项目的核心解耦点：**前端只认这个接口，不关心数据存在哪**。
 *
 * 于是同一份前端代码，可以跑在三种后端上：
 *   ① LocalAdapter   —— 数据存浏览器（现在的做法，零后端）
 *   ② HttpAdapter    —— 数据存云端（多家庭共享，需后端）
 *   ③ （未来）SyncAdapter —— 本地优先 + 云端同步
 *
 * 设计原则（对应项目红线）：
 *   - 离线优先：任何适配器都必须能在断网时读到最后一次的数据
 *   - 数据自主：LocalAdapter 一行都不上网
 *   - 可迁移：换后端不需要改前端业务代码
 */

/** @typedef {'语文'|'数学'|'英语'|'物理'|'化学'|'生物'|'历史'|'地理'|'道法'|'其他'} Subject */

/**
 * @typedef {Object} KnowledgeCard 知识卡
 * @property {string} id
 * @property {string} front      正面：问题（写问题比写名词有效）
 * @property {string} back       背面：孩子自己的解释
 * @property {Subject} subject
 * @property {number} step       当前间隔步数（索引 STEPS）
 * @property {string} due        下次复习日期 YYYY-MM-DD
 * @property {number} okCount    累计答对次数
 * @property {string} createdAt
 */

/**
 * @typedef {Object} ErrorItem 错题
 * @property {string} id
 * @property {string} question   题目（可简写）
 * @property {string} thinking   ★最关键：我当时是怎么想的
 * @property {string} gap        正确思路差在哪一步
 * @property {string} type       错因类型（单选）
 * @property {number} round      已做对次数（3 次归档）
 * @property {string} due
 * @property {boolean} archived
 */

/**
 * @typedef {Object} KidProfile 孩子档案
 * @property {string} id
 * @property {string} nickname   ★合规：只存昵称，不存真实姓名
 * @property {'low'|'high'|'mid'|'senior'} stage
 * @property {string} createdAt
 */

/**
 * 所有适配器必须实现的接口
 * @interface DataAdapter
 */
export const ADAPTER_METHODS = [
  // 知识卡
  'listCards',      // (kidId) => Promise<KnowledgeCard[]>
  'addCard',        // (kidId, card) => Promise<KnowledgeCard>
  'gradeCard',      // (kidId, cardId, remembered:boolean) => Promise<KnowledgeCard>
  'deleteCard',     // (kidId, cardId) => Promise<void>
  // 错题
  'listErrors',     // (kidId) => Promise<ErrorItem[]>
  'addError',       // (kidId, item) => Promise<ErrorItem>
  'resolveError',   // (kidId, errId) => Promise<ErrorItem>
  'deleteError',    // (kidId, errId) => Promise<void>
  // 档案
  'getKid',         // (kidId) => Promise<KidProfile|null>
  'saveKid',        // (profile) => Promise<KidProfile>
  // 合规
  'exportAll',      // (kidId) => Promise<Object>  数据可携带
  'deleteAll',      // (kidId) => Promise<void>    数据可删除（未成年人必须能删）
];

/* ============================================================
   间隔复习算法 —— 单一事实来源
   两个适配器共用，保证换后端不会改变复习行为
   ============================================================ */

/** 知识卡间隔（天）：儿童版，比成人密 */
export const CARD_STEPS = [0, 2, 4, 7, 15, 30];

/** 错题重做间隔（天）：需连续做对 3 次 */
export const ERROR_STEPS = [3, 7, 15];

export function todayStr(d = new Date()) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
}

export function addDays(days, from = new Date()) {
  const d = new Date(from);
  d.setDate(d.getDate() + days);
  return todayStr(d);
}

export function nextCardDue(step) {
  return addDays(CARD_STEPS[Math.min(step, CARD_STEPS.length - 1)]);
}

export function nextErrorDue(round) {
  return addDays(ERROR_STEPS[Math.min(round, ERROR_STEPS.length - 1)]);
}

export function isDue(item, now = todayStr()) {
  return item.due <= now;
}

/** 答对：前进一档 */
export function advanceCard(card) {
  const step = card.step + 1;
  return { ...card, step, okCount: card.okCount + 1, due: nextCardDue(step) };
}

/** 答错：回退两档（但不低于 0），明天再来 */
export function regressCard(card) {
  const step = Math.max(0, card.step - 2);
  return { ...card, step, due: addDays(1) };
}

/** 错题做对一次：round+1，满 3 次归档
 *  注意：archived 永远返回布尔值（不要返回 undefined，否则数据库存 NaN 且前端判断失效） */
export function resolveErrorOnce(item) {
  const round = item.round + 1;
  if (round >= ERROR_STEPS.length) {
    return { round, archived: true, due: item.due };
  }
  return { round, archived: false, due: nextErrorDue(round) };
}

/** 生成短 id（避免依赖 crypto，兼容老设备） */
export function makeId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}
