/**
 * 数据迁移：旧格式（v1）→ 新格式（adapter v1）
 * ============================================
 * 旧格式（线上已有用户可能存过）：
 *   { cards:[{front,back,sub,step,due,ok}], errs:[{q,think,gap,type,round,due,done}], kid:{name,stage} }
 *
 * 新格式：
 *   { kids:{}, cards:{}, errors:{} }
 *
 * 设计原则：
 *   1. 迁移是幂等的（跑两次结果一样）
 *   2. 迁移前备份旧数据（万一出错能回滚）
 *   3. 迁移后不删除旧键（保守起见，保留一段时间）
 *   4. 解析失败不抛异常，返回"无需迁移"
 */

export const LEGACY_KEY = 'learnos.v1';
export const BACKUP_SUFFIX = '.backup-pre-migration';

/**
 * 检测是否存在需要迁移的旧数据
 * @returns {{needs:boolean, reason:string, counts?:object}}
 */
export function detectLegacy(storage) {
  let raw;
  try { raw = storage.getItem(LEGACY_KEY); }
  catch { return { needs: false, reason: 'storage 不可读' }; }

  if (!raw) return { needs: false, reason: '无旧数据' };

  let old;
  try { old = JSON.parse(raw); }
  catch { return { needs: false, reason: '旧数据解析失败（可能已损坏）' }; }

  const hasCards = Array.isArray(old.cards) && old.cards.length > 0;
  const hasErrs = Array.isArray(old.errs) && old.errs.length > 0;
  // 注意：stage:'low' 是旧版默认值之一，单独出现不算"有数据"。
  // 只有真的填了名字，或填了非默认学段，才算用户真实录入过。
  const name = (old.kid?.name || '').trim();
  const stage = old.kid?.stage;
  const hasKid = name.length > 0 || (stage && stage !== 'low');

  if (!hasCards && !hasErrs && !hasKid) {
    return { needs: false, reason: '旧数据为空（仅默认值）' };
  }
  return {
    needs: true,
    reason: '发现旧版数据',
    counts: { cards: (old.cards || []).length, errors: (old.errs || []).length,
              kid: hasKid ? 1 : 0 },
  };
}


/** 本地时区的 YYYY-MM-DD
 *  ⚠️ 不要用 toISOString()——它返回 UTC，中国 UTC+8 下
 *  凌晨 0:00-8:00 会得到前一天。 */
function localDateStr(d = new Date()) {
  const x = d instanceof Date ? d : new Date(d);
  return new Date(x.getTime() - x.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
}

/** 生成稳定的迁移 id（可重复执行不产生重复记录） */
function legacyId(prefix, i, seed) {
  return `${prefix}_migrated_${i}_${String(seed).replace(/\W/g, '').slice(0, 8)}`;
}

/**
 * 执行迁移。纯函数式：接收旧数据，返回新格式，不改动入参。
 * @param {object} old 旧格式对象
 * @param {number} now 时间戳（便于测试）
 * @returns {{kids:object, cards:object, errors:object, kidId:string}}
 */
export function migrate(old, now = Date.now()) {
  const kids = {}, cards = {}, errors = {};

  const stage = ['low', 'high', 'mid', 'senior'].includes(old?.kid?.stage)
    ? old.kid.stage : 'low';
  const nickname = (old?.kid?.name || '').trim() || '孩子';
  const kidId = 'kid_migrated';

  kids[kidId] = {
    id: kidId,
    nickname,
    stage,
    createdAt: new Date(now).toISOString(),
    migratedFrom: 'v1',
  };

  (old?.cards || []).forEach((c, i) => {
    if (!c || typeof c !== 'object') return;
    const id = c.id || legacyId('c', i, c.front || '');
    cards[id] = {
      id, kidId,
      front: String(c.front ?? ''),
      back: String(c.back ?? ''),
      subject: String(c.sub ?? c.subject ?? '其他'),
      step: Number.isFinite(c.step) ? c.step : 0,
      okCount: Number.isFinite(c.ok) ? c.ok : (Number.isFinite(c.okCount) ? c.okCount : 0),
      // ⚠️ 必须用本地时区：toISOString 返回 UTC，
      // 中国 UTC+8 下凌晨 0-8 点会算成前一天
      due: typeof c.due === 'string' ? c.due : localDateStr(now),
      createdAt: c.createdAt || new Date(now).toISOString(),
    };
  });

  (old?.errs || []).forEach((e, i) => {
    if (!e || typeof e !== 'object') return;
    const id = e.id || legacyId('e', i, e.q || '');
    errors[id] = {
      id, kidId,
      question: String(e.q ?? e.question ?? ''),
      thinking: String(e.think ?? e.thinking ?? ''),
      gap: String(e.gap ?? ''),
      type: String(e.type ?? '概念不懂'),
      round: Number.isFinite(e.round) ? e.round : 0,
      due: typeof e.due === 'string' ? e.due : localDateStr(now),
      archived: e.done === true || e.archived === true,
      createdAt: e.createdAt || new Date(now).toISOString(),
    };
  });

  return { kids, cards, errors, kidId };
}

/**
 * 在真实 storage 上执行迁移（含备份）
 * @returns {{migrated:boolean, kidId?:string, counts?:object, backupKey?:string, reason?:string}}
 */
export function runMigration(storage, now = Date.now()) {
  const det = detectLegacy(storage);
  if (!det.needs) return { migrated: false, reason: det.reason };

  const raw = storage.getItem(LEGACY_KEY);
  const backupKey = LEGACY_KEY + BACKUP_SUFFIX;

  try {
    // 1. 先备份（幂等：已有备份就不覆盖，保留最早的）
    if (!storage.getItem(backupKey)) storage.setItem(backupKey, raw);

    // 2. 迁移
    const old = JSON.parse(raw);
    const next = migrate(old, now);

    // 3. 写入新键
    storage.setItem('learnos.adapter.local.v1', JSON.stringify({
      kids: next.kids, cards: next.cards, errors: next.errors,
    }));

    // 4. 记住当前档案
    storage.setItem('learnos.currentKid', next.kidId);

    return {
      migrated: true,
      kidId: next.kidId,
      counts: det.counts,
      backupKey,
    };
  } catch (e) {
    return { migrated: false, reason: '迁移失败: ' + (e?.message || e) };
  }
}
