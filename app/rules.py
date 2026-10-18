"""운영 규칙. 화면이 아니라 여기서 강제해요."""
import re

from . import db
from .config import CHANNELS, COMMENT, DAILY_MAX, TEST_VIDEOS


class RuleError(Exception):
    pass


# 이 상태의 기록이 있으면 그 영상에는 더 달지 않아요. unverified는 실제로 올라갔을 수 있어서 포함해요.
OCCUPYING = ("queued", "opening", "typing", "submitted", "unverified", "posted")
_IN = ",".join(f"'{s}'" for s in OCCUPYING)


def allowed_video(video_id: str, channel_id: str | None) -> bool:
    return video_id in TEST_VIDEOS or channel_id in CHANNELS


def posted_today() -> int:
    """오늘 쓴 게시 슬롯. 진행 중이거나 확인이 필요한 것도 세요."""
    with db.tx() as c:
        return c.execute(
            f"SELECT COUNT(*) FROM posts WHERE status IN ({_IN}) AND date(created_at)=date('now','localtime')"
        ).fetchone()[0]


def already_posted(video_id: str) -> bool:
    with db.tx() as c:
        return c.execute(f"SELECT 1 FROM posts WHERE video_id=? AND status IN ({_IN})",
                         (video_id,)).fetchone() is not None


LINK = re.compile(r"(https?://|www\.|bit\.ly|youtu\.?be|\.(com|net|kr|me|io|ly|co|org)\b)", re.I)
# 운명원을 직접 이용해 본 것처럼 쓰는 후기 (소문·궁금·계획 톤은 허용)
FAKE_REVIEW = re.compile(
    COMMENT["brand"] + r".{0,20}(가봤|가 봤|갔다 왔|다녀왔|다녀 왔|봤는데|봤더니|받아봤|받아 봤|받았는데|후기|용하더라|용했|맞더라|맞았|맞춰서|추천해)"
    r"|(가봤|다녀왔|받아봤|봤는데).{0,15}" + COMMENT["brand"])


def check_comment(text: str) -> list[dict]:
    """초안 규칙 검사. 대시보드에 그대로 보여줘요."""
    n = len(text.strip())
    brand = COMMENT["brand"]
    return [
        {"rule": f"{COMMENT['min_chars']}~{COMMENT['max_chars']}자", "ok": COMMENT["min_chars"] <= n <= COMMENT["max_chars"], "detail": f"{n}자"},
        {"rule": "링크 없음", "ok": not LINK.search(text)},
        {"rule": "해시태그 없음", "ok": "#" not in text},
        {"rule": f"{brand} 언급", "ok": brand in text},
        {"rule": "이용 후기처럼 쓰지 않음", "ok": not FAKE_REVIEW.search(text)},
    ]


def assert_can_post(video_id: str, channel_id: str | None, text: str):
    if not allowed_video(video_id, channel_id):
        raise RuleError("허용된 채널(또는 테스트 영상)이 아니에요.")
    if already_posted(video_id):
        raise RuleError("이 영상에는 이미 댓글을 달았거나 게시 확인이 필요해요. 영상당 1개까지예요.")
    if posted_today() >= DAILY_MAX:
        raise RuleError(f"오늘 게시 상한({DAILY_MAX}개)에 도달했어요.")
    failed = [c["rule"] for c in check_comment(text) if not c["ok"]]
    if failed:
        raise RuleError("댓글 규칙 위반: " + ", ".join(failed))
