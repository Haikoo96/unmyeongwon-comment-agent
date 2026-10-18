from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, poster, rules, youtube
from .agents import pipeline
from .config import CHANNELS, DAILY_MAX, PROFILES, ROOT, SCREENSHOTS_DIR

app = FastAPI(title="운명원 댓글 에이전트")
db.init()


def _video(video_id: str) -> dict:
    with db.tx() as c:
        v = db.row(c.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())
    if not v:
        raise HTTPException(404, "먼저 영상을 불러와 주세요.")
    if not rules.allowed_video(v["id"], v["channel_id"]):
        raise HTTPException(403, "허용된 채널의 영상이 아니에요.")
    return v


@app.get("/api/status")
def status():
    return {"posted_today": rules.posted_today(), "daily_max": DAILY_MAX,
            "channels": CHANNELS, "profiles": PROFILES, "posting": poster.POST_LOCK.locked()}


@app.post("/api/videos/load")
def load_videos():
    try:
        youtube.fetch_latest_videos()
    except Exception as e:
        raise HTTPException(400, str(e))
    return list_videos()


@app.get("/api/videos")
def list_videos():
    occupied = ",".join(f"'{s}'" for s in rules.OCCUPYING)
    with db.tx() as c:
        rows = c.execute(
            f"""SELECT v.*, EXISTS(SELECT 1 FROM posts p WHERE p.video_id=v.id AND p.status IN ({occupied})) AS posted
               FROM videos v ORDER BY published_at DESC""").fetchall()
    return [dict(r) for r in rows if rules.allowed_video(r["id"], r["channel_id"])]


class LinkIn(BaseModel):
    url: str


@app.post("/api/videos/link")
def add_link(body: LinkIn):
    vid = youtube.parse_video_id(body.url.strip())
    if not vid:
        raise HTTPException(400, "유튜브 링크 형식이 아니에요.")
    try:
        v = youtube.fetch_video(vid)
    except Exception as e:  # 없는 영상, API 오류 (키는 메시지에 들어가지 않아요)
        raise HTTPException(400, str(e))
    if not rules.allowed_video(v["id"], v["channel_id"]):
        raise HTTPException(403, f"'{v['channel_title']}'은 허용된 채널이 아니라서 댓글을 달 수 없어요.")
    youtube.save_video(v)  # 울타리를 통과한 영상만 저장해요
    return v


@app.get("/api/videos/{video_id}/analysis")
def get_analysis(video_id: str):
    _video(video_id)
    with db.tx() as c:
        r = c.execute("SELECT * FROM analyses WHERE video_id=? ORDER BY id DESC LIMIT 1", (video_id,)).fetchone()
    return db.row(r)


@app.post("/api/videos/{video_id}/analyze")
def analyze(video_id: str):
    _video(video_id)
    try:
        return pipeline.run(video_id)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/videos/{video_id}/rewrite")
def rewrite(video_id: str):
    """페르소나·여정은 그대로 두고 댓글만 다시 써요."""
    _video(video_id)
    try:
        return pipeline.rewrite(video_id)
    except Exception as e:
        raise HTTPException(500, str(e))


class CheckIn(BaseModel):
    text: str


@app.post("/api/check")
def check(body: CheckIn):
    return rules.check_comment(body.text)


class PostIn(BaseModel):
    video_id: str
    profile: str
    text: str


@app.post("/api/posts")
def create_post(body: PostIn):
    if body.profile not in PROFILES:
        raise HTTPException(400, "알 수 없는 프로필이에요.")
    if not poster.POST_LOCK.acquire(blocking=False):
        raise HTTPException(409, "다른 댓글을 게시하는 중이에요. 끝난 뒤에 다시 눌러 주세요.")
    try:
        with db.tx() as c:
            v = c.execute("SELECT channel_id FROM videos WHERE id=?", (body.video_id,)).fetchone()
        rules.assert_can_post(body.video_id, v["channel_id"] if v else None, body.text)
        with db.tx() as c:
            post_id = c.execute("INSERT INTO posts (video_id, profile, text, status) VALUES (?,?,?, 'queued')",
                                (body.video_id, body.profile, body.text)).lastrowid
    except rules.RuleError as e:
        poster.POST_LOCK.release()
        raise HTTPException(403, str(e))
    except Exception:
        poster.POST_LOCK.release()
        raise
    poster.start(post_id, body.video_id, body.profile, body.text)  # 스레드가 끝나면 락을 풀어요
    return {"id": post_id}


@app.get("/api/posts")
def list_posts():
    with db.tx() as c:
        rows = c.execute(
            """SELECT p.*, v.title, v.channel_title FROM posts p LEFT JOIN videos v ON v.id=p.video_id
               ORDER BY p.id DESC LIMIT 100""").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/posts/{post_id}")
def get_post(post_id: int):
    with db.tx() as c:
        r = c.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not r:
        raise HTTPException(404)
    return dict(r)


class ResolveIn(BaseModel):
    posted: bool


@app.post("/api/posts/{post_id}/resolve")
def resolve(post_id: int, body: ResolveIn):
    """확인 필요(unverified) 기록을 사람이 영상에서 확인한 뒤 정리해요."""
    with db.tx() as c:
        r = c.execute("SELECT status FROM posts WHERE id=?", (post_id,)).fetchone()
        if not r or r["status"] != "unverified":
            raise HTTPException(400, "확인이 필요한 기록이 아니에요.")
        if body.posted:
            c.execute("UPDATE posts SET status='posted', error='영상에서 직접 확인했어요.', "
                      "updated_at=datetime('now','localtime') WHERE id=?", (post_id,))
        else:
            c.execute("UPDATE posts SET status='failed', error='영상에서 확인해 보니 올라가지 않았어요.', "
                      "updated_at=datetime('now','localtime') WHERE id=?", (post_id,))
    return get_post(post_id)


app.mount("/shots", StaticFiles(directory=SCREENSHOTS_DIR), name="shots")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")
