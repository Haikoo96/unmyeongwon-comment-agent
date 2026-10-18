"""오케스트레이션. 순서가 정해진 파이프라인이라 코드로 직접 이어요.

영상 → [Agent 1 페르소나] → [Agent 2 여정] → [Agent 3 댓글] → 규칙 검사(실패 시 1회 재작성) → DB 저장
다시 쓰기는 저장된 페르소나·여정으로 Agent 3만 다시 돌려요.
"""
from .. import db, rules, youtube
from ..config import LLM
from . import context, persona, writer


def _video(video_id: str) -> dict:
    with db.tx() as c:
        video = db.row(c.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())
    if not video:
        raise ValueError("먼저 영상을 불러와 주세요.")
    return video


def _recent_drafts(n: int = 6) -> list[str]:
    """다른 영상에 쓴 최근 초안. 같은 틀이 반복되지 않게 작가에게 보여줘요."""
    with db.tx() as c:
        return [r[0] for r in c.execute(
            "SELECT draft FROM analyses WHERE draft IS NOT NULL ORDER BY id DESC LIMIT ?", (n,))]


def _write(video, p, j, transcript_used, previous: str | None = None) -> tuple[writer.Draft, list[dict]]:
    recent = _recent_drafts()
    feedback = f"이전 초안 '{previous}'과 다른 구조와 표현으로 새로 써." if previous else None
    d = writer.run(video, p, j, transcript_used, recent, feedback)
    checks = rules.check_comment(d.text)
    failed = [c["rule"] for c in checks if not c["ok"]]
    if failed:
        d = writer.run(video, p, j, transcript_used, recent,
                       f"이전 초안 '{d.text}'이 규칙 위반: {', '.join(failed)}. 고쳐서 다시 써.")
        checks = rules.check_comment(d.text)
    return d, checks


def _save(video_id, p: persona.PersonaResult, j: context.Journey, d: writer.Draft, checks, transcript_used) -> dict:
    with db.tx() as c:
        cur = c.execute(
            """INSERT INTO analyses (video_id, worry, transcript_used, key_scenes, persona, evidence, filtered,
                                     journey, draft, scene, checks, model)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (video_id, p.worry, int(transcript_used), db.dumps(p.key_scenes),
             db.dumps(p.persona.model_dump() | {"confidence": p.confidence}), db.dumps(p.evidence),
             db.dumps([f.model_dump() for f in p.filtered]), db.dumps(j.model_dump()),
             d.text, d.scene, db.dumps(checks), LLM["model"]),
        )
        return db.row(c.execute("SELECT * FROM analyses WHERE id=?", (cur.lastrowid,)).fetchone())


def run(video_id: str) -> dict:
    video = _video(video_id)
    transcript = youtube.fetch_transcript(video_id)
    comments = youtube.fetch_comments(video_id)

    p = persona.run(video, transcript, comments)
    j = context.run(p)
    d, checks = _write(video, p, j, transcript is not None)
    return _save(video_id, p, j, d, checks, transcript is not None)


def rewrite(video_id: str) -> dict:
    video = _video(video_id)
    with db.tx() as c:
        a = db.row(c.execute("SELECT * FROM analyses WHERE video_id=? ORDER BY id DESC LIMIT 1",
                             (video_id,)).fetchone())
    if not a or not a.get("key_scenes"):
        return run(video_id)  # 예전 형식이면 처음부터 분석해요

    pers = dict(a["persona"])
    confidence = pers.pop("confidence", "낮음")
    p = persona.PersonaResult(worry=a["worry"], key_scenes=a["key_scenes"], filtered=a["filtered"] or [],
                              evidence=a["evidence"] or [], confidence=confidence, persona=pers)
    j = context.Journey(**a["journey"])
    transcript_used = bool(a["transcript_used"])
    d, checks = _write(video, p, j, transcript_used, previous=a["draft"])
    return _save(video_id, p, j, d, checks, transcript_used)
