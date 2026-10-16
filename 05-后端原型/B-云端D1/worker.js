/**
 * Cloudflare Worker + D1 —— 方案 B 的后端
 * =========================================
 * 部署：wrangler deploy
 * 数据库：wrangler d1 create learnos-db
 *
 * 设计取舍（对应"面向很多家庭 + 合规"）：
 *   1. 匿名优先：不收集真实姓名、手机号、身份证。孩子只用昵称。
 *   2. 家长同意：创建档案时必须显式确认（consent_at 落库）。
 *   3. 数据可携可删：GET /export 全量导出；DELETE /kids/:id 彻底删除。
 *   4. 最小留存：不记录 IP、不记录 UA 到业务表。
 *   5. 令牌短时效：30 天，可撤销。
 */

import {
  nextCardDue, nextErrorDue, addDays, todayStr,
  advanceCard, regressCard, resolveErrorOnce,
} from '../contract.js';

/* ---------------- 工具 ---------------- */

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,DELETE,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type,Authorization',
      'Cache-Control': 'no-store',
    },
  });

const err = (msg, status = 400) => json({ error: msg }, status);

const uid = (p = '') =>
  p + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

/** 校验：只允许预期字段，防止越权写入 */
function pick(obj, keys) {
  const out = {};
  for (const k of keys) if (obj[k] !== undefined) out[k] = obj[k];
  return out;
}

/* ---------------- 路由 ---------------- */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    if (method === 'OPTIONS') return json({}, 204);

    try {
      // 健康检查
      if (path === '/api/health') return json({ ok: true, ts: Date.now() });

      // 合规：家长同意说明（供前端展示）
      if (path === '/api/consent-notice') {
        return json({
          collects: ['孩子昵称', '学习卡内容', '错题记录'],
          neverCollects: ['真实姓名', '手机号', '身份证', '精确位置', 'IP 画像'],
          rights: ['随时导出全部数据', '随时彻底删除', '不需要真实身份即可使用'],
          retention: '用户主动删除后立即物理删除',
        });
      }

      // 登录（极简：用家庭码换令牌；真实产品应接入微信/手机号）
      if (path === '/api/login' && method === 'POST') {
        const { familyCode } = await request.json();
        if (!familyCode) return err('缺少家庭码');
        const fam = await env.DB.prepare(
          'SELECT id FROM families WHERE code = ?'
        ).bind(familyCode).first();
        if (!fam) return err('家庭码无效', 401);
        const token = uid('tk_');
        await env.DB.prepare(
          'INSERT INTO sessions (token, family_id, created_at, expires_at) VALUES (?,?,?,?)'
        ).bind(token, fam.id, Date.now(), Date.now() + 30 * 864e5).run();
        return json({ token, familyId: fam.id });
      }

      // ---- 以下均需鉴权 ----
      const auth = request.headers.get('Authorization') || '';
      const token = auth.replace(/^Bearer\s+/, '');
      if (!token) return err('未登录', 401);

      const sess = await env.DB.prepare(
        'SELECT family_id FROM sessions WHERE token = ? AND expires_at > ?'
      ).bind(token, Date.now()).first();
      if (!sess) return err('登录已失效', 401);
      const familyId = sess.family_id;

      // 创建孩子档案（合规：需显式同意）
      if (path === '/api/kids' && method === 'POST') {
        const body = await request.json();
        const d = pick(body, ['nickname', 'stage', 'consent']);
        if (!d.nickname) return err('昵称必填');
        if (d.consent !== true) return err('必须确认家长同意才能创建档案', 403);
        if (!['low', 'high', 'mid', 'senior'].includes(d.stage)) return err('学段不合法');

        const id = uid('kid_');
        await env.DB.prepare(
          `INSERT INTO kids (id, family_id, nickname, stage, consent_at, created_at)
           VALUES (?,?,?,?,?,?)`
        ).bind(id, familyId, d.nickname, d.stage, Date.now(), Date.now()).run();
        return json({ id, nickname: d.nickname, stage: d.stage });
      }

      // 校验孩子归属本家庭（防越权）
      const kidMatch = path.match(/^\/api\/kids\/([^/]+)/);
      if (!kidMatch) return err('未知路径', 404);
      const kidId = kidMatch[1];

      const kid = await env.DB.prepare(
        'SELECT * FROM kids WHERE id = ? AND family_id = ?'
      ).bind(kidId, familyId).first();
      if (!kid) return err('档案不存在或无权访问', 404);

      if (path === `/api/kids/${kidId}` && method === 'GET') {
        return json(kid);
      }

      // 合规：彻底删除（物理删除，非软删）
      if (path === `/api/kids/${kidId}` && method === 'DELETE') {
        await env.DB.batch([
          env.DB.prepare('DELETE FROM cards WHERE kid_id = ?').bind(kidId),
          env.DB.prepare('DELETE FROM errors WHERE kid_id = ?').bind(kidId),
          env.DB.prepare('DELETE FROM kids WHERE id = ?').bind(kidId),
        ]);
        return json({ deleted: true });
      }

      // 合规：数据可携带
      if (path === `/api/kids/${kidId}/export` && method === 'GET') {
        const [cards, errors] = await Promise.all([
          env.DB.prepare('SELECT * FROM cards WHERE kid_id = ?').bind(kidId).all(),
          env.DB.prepare('SELECT * FROM errors WHERE kid_id = ?').bind(kidId).all(),
        ]);
        return json({
          exportedAt: new Date().toISOString(),
          kid, cards: cards.results, errors: errors.results,
        });
      }

      /* ---------- 知识卡 ---------- */
      if (path === `/api/kids/${kidId}/cards`) {
        if (method === 'GET') {
          const r = await env.DB.prepare(
            'SELECT * FROM cards WHERE kid_id = ? ORDER BY created_at DESC'
          ).bind(kidId).all();
          return json(r.results);
        }
        if (method === 'POST') {
          const b = await request.json();
          const d = pick(b, ['front', 'back', 'subject']);
          if (!d.front || !d.back) return err('正反面都要填');
          const id = uid('c_');
          const today = todayStr();
          await env.DB.prepare(
            `INSERT INTO cards (id, kid_id, front, back, subject, step, ok_count, due, created_at)
             VALUES (?,?,?,?,?,0,0,?,?)`
          ).bind(id, kidId, d.front, d.back, d.subject || '其他', today, Date.now()).run();
          return json({ id, kid_id: kidId, ...d, step: 0, ok_count: 0, due: today });
        }
      }

      const cardGrade = path.match(new RegExp(`^/api/kids/${kidId}/cards/([^/]+)/grade$`));
      if (cardGrade && method === 'POST') {
        const cardId = cardGrade[1];
        const { remembered } = await request.json();
        const row = await env.DB.prepare(
          'SELECT * FROM cards WHERE id = ? AND kid_id = ?'
        ).bind(cardId, kidId).first();
        if (!row) return err('卡片不存在', 404);

        const cur = { step: row.step, okCount: row.ok_count };
        const next = remembered ? advanceCard(cur) : regressCard(cur);
        await env.DB.prepare(
          'UPDATE cards SET step = ?, ok_count = ?, due = ? WHERE id = ?'
        ).bind(next.step, next.okCount, next.due, cardId).run();
        return json({ ...row, step: next.step, ok_count: next.okCount, due: next.due });
      }

      const cardDel = path.match(new RegExp(`^/api/kids/${kidId}/cards/([^/]+)$`));
      if (cardDel && method === 'DELETE') {
        await env.DB.prepare('DELETE FROM cards WHERE id = ? AND kid_id = ?')
          .bind(cardDel[1], kidId).run();
        return json({ deleted: true });
      }

      /* ---------- 错题 ---------- */
      if (path === `/api/kids/${kidId}/errors`) {
        if (method === 'GET') {
          const r = await env.DB.prepare(
            'SELECT * FROM errors WHERE kid_id = ? ORDER BY created_at DESC'
          ).bind(kidId).all();
          return json(r.results);
        }
        if (method === 'POST') {
          const b = await request.json();
          const d = pick(b, ['question', 'thinking', 'gap', 'type']);
          if (!d.question) return err('题目必填');
          const id = uid('e_');
          await env.DB.prepare(
            `INSERT INTO errors (id, kid_id, question, thinking, gap, type, round, due, archived, created_at)
             VALUES (?,?,?,?,?,?,0,?,0,?)`
          ).bind(id, kidId, d.question, d.thinking || '', d.gap || '',
                 d.type || '概念不懂', addDays(3), Date.now()).run();
          return json({ id, kid_id: kidId, ...d, round: 0, archived: false, due: addDays(3) });
        }
      }

      const errResolve = path.match(new RegExp(`^/api/kids/${kidId}/errors/([^/]+)/resolve$`));
      if (errResolve && method === 'POST') {
        const errId = errResolve[1];
        const row = await env.DB.prepare(
          'SELECT * FROM errors WHERE id = ? AND kid_id = ?'
        ).bind(errId, kidId).first();
        if (!row) return err('错题不存在', 404);

        const next = resolveErrorOnce({ round: row.round });
        await env.DB.prepare(
          'UPDATE errors SET round = ?, due = ?, archived = ? WHERE id = ?'
        ).bind(next.round, next.due ?? row.due, next.archived ? 1 : 0, errId).run();
        return json({ ...row, round: next.round, archived: next.archived });
      }

      const errDel = path.match(new RegExp(`^/api/kids/${kidId}/errors/([^/]+)$`));
      if (errDel && method === 'DELETE') {
        await env.DB.prepare('DELETE FROM errors WHERE id = ? AND kid_id = ?')
          .bind(errDel[1], kidId).run();
        return json({ deleted: true });
      }

      return err('未知路径', 404);
    } catch (e) {
      return err('服务器错误: ' + (e?.message || e), 500);
    }
  },
};
