"""SQLite 저장소. 대시보드가 보여주는 모든 것(영상, 분석, 초안, 게시 기록, 여정 재료)이 여기 있어요."""
import json
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id            TEXT PRIMARY KEY,          -- YouTube video id
    channel_id    TEXT NOT NULL,
    channel_title TEXT,
    title         TEXT,
    description   TEXT,
    thumbnail     TEXT,
    published_at  TEXT,
    fetched_at    TEXT DEFAULT (datetime('now','localtime'))
);

-- Agent 1~3 결과. 영상마다 여러 번 돌릴 수 있고, 최신 것이 화면에 나와요.
CREATE TABLE IF NOT EXISTS analyses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL REFERENCES videos(id),
    worry       TEXT,       -- 영상 속 고민 한 줄
    transcript_used INTEGER, -- 1: 자막 기반, 0: 제목·설명 기반
    key_scenes  TEXT,       -- JSON: 영상 속 장면·대사
    persona     TEXT,       -- JSON: Agent 1 페르소나
    evidence    TEXT,       -- JSON: 근거가 된 진짜 시청자 댓글
    filtered    TEXT,       -- JSON: 걸러낸 의심 댓글과 이유
    journey     TEXT,       -- JSON: Agent 2 삶의 여정 + 운명원 다리
    draft       TEXT,       -- Agent 3 댓글 초안
    scene       TEXT,       -- 초안이 짚은 영상 장면
    checks      TEXT,       -- JSON: 규칙 검사 결과
    model       TEXT,
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

-- 게시 시도 기록 (성공/실패 모두). 운영 규칙의 근거가 돼요.
CREATE TABLE IF NOT EXISTS posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL,
    profile     TEXT NOT NULL,
    text        TEXT NOT NULL,
    status      TEXT NOT NULL,   -- queued / opening / typing / submitted / posted / failed / unverified
    error       TEXT,
    screenshot  TEXT,
    comment_url TEXT,            -- 내 댓글로 바로 가는 링크 (lc=)
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);
-- 영상당 성공 게시는 1개만 (DB 차원에서도 막아요)
CREATE UNIQUE INDEX IF NOT EXISTS one_post_per_video ON posts(video_id) WHERE status = 'posted';

-- 컨텍스트 헌팅 재료 (네이트판, 수동 투입 등). 향후 여정 라이브러리로 커져요.
CREATE TABLE IF NOT EXISTS snippets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,   -- natepann / youtube / manual / threads ...
    url         TEXT,
    text        TEXT NOT NULL,
    tags        TEXT,            -- 쉼표 구분: 읽씹, 재회, 짝사랑 ...
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);
"""

JSON_FIELDS = {"persona", "evidence", "filtered", "journey", "checks", "key_scenes"}

# 예전 DB에 없던 컬럼
MIGRATIONS = {
    "analyses": {"transcript_used": "INTEGER", "key_scenes": "TEXT"},
    "posts": {"comment_url": "TEXT"},
}


def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def tx():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with tx() as c:
        c.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for col, typ in cols.items():
                if col not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        # 서버가 게시 도중에 꺼졌다면 멈춘 기록을 정리해요
        c.execute("""UPDATE posts SET status='failed', error='서버가 재시작되어 게시가 중단됐어요.'
                     WHERE status IN ('queued','opening','typing')""")
        c.execute("""UPDATE posts SET status='unverified',
                     error='게시 버튼을 누른 뒤 서버가 꺼졌어요. 영상에서 직접 확인해 주세요.'
                     WHERE status='submitted'""")


def row(r):
    if r is None:
        return None
    d = dict(r)
    for k in JSON_FIELDS & d.keys():
        if d[k]:
            d[k] = json.loads(d[k])
    return d


def dumps(v):
    return json.dumps(v, ensure_ascii=False)
