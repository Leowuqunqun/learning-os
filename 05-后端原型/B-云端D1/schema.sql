-- 学习操作系统 · D1 (SQLite) 表结构
-- 应用：wrangler d1 execute learnos-db --file=./schema.sql

-- 家庭（一个家庭一个码，不绑定真实身份）
CREATE TABLE IF NOT EXISTS families (
  id         TEXT PRIMARY KEY,
  code       TEXT UNIQUE NOT NULL,        -- 家庭码，家长之间自己分发给家人
  created_at INTEGER NOT NULL
);

-- 会话令牌（30 天，可撤销）
CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  family_id  TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  FOREIGN KEY (family_id) REFERENCES families(id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_exp ON sessions(expires_at);

-- 孩子档案（合规：只存昵称，不存真实姓名）
CREATE TABLE IF NOT EXISTS kids (
  id         TEXT PRIMARY KEY,
  family_id  TEXT NOT NULL,
  nickname   TEXT NOT NULL,               -- 昵称即可
  stage      TEXT NOT NULL,               -- low|high|mid|senior
  consent_at INTEGER NOT NULL,            -- ★家长同意时间戳（合规必需）
  created_at INTEGER NOT NULL,
  FOREIGN KEY (family_id) REFERENCES families(id)
);
CREATE INDEX IF NOT EXISTS idx_kids_family ON kids(family_id);

-- 知识卡
CREATE TABLE IF NOT EXISTS cards (
  id         TEXT PRIMARY KEY,
  kid_id     TEXT NOT NULL,
  front      TEXT NOT NULL,
  back       TEXT NOT NULL,
  subject    TEXT NOT NULL DEFAULT '其他',
  step       INTEGER NOT NULL DEFAULT 0,
  ok_count   INTEGER NOT NULL DEFAULT 0,
  due        TEXT NOT NULL,               -- YYYY-MM-DD
  created_at INTEGER NOT NULL,
  FOREIGN KEY (kid_id) REFERENCES kids(id)
);
CREATE INDEX IF NOT EXISTS idx_cards_kid_due ON cards(kid_id, due);

-- 错题
CREATE TABLE IF NOT EXISTS errors (
  id         TEXT PRIMARY KEY,
  kid_id     TEXT NOT NULL,
  question   TEXT NOT NULL,
  thinking   TEXT NOT NULL DEFAULT '',    -- ★我当时是怎么想的（本项目最看重的一栏）
  gap        TEXT NOT NULL DEFAULT '',
  type       TEXT NOT NULL DEFAULT '概念不懂',
  round      INTEGER NOT NULL DEFAULT 0,
  due        TEXT NOT NULL,
  archived   INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (kid_id) REFERENCES kids(id)
);
CREATE INDEX IF NOT EXISTS idx_errors_kid_due ON errors(kid_id, due);
