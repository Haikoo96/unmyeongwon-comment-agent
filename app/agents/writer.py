"""Agent 3. 댓글 작가: 영상 장면 + 내 고민 공감 + 운명원 넛지."""
import json
from typing import Literal

from pydantic import BaseModel, Field

from ..config import COMMENT
from ..llm import ask
from .context import Journey
from .persona import PersonaResult

BRAND = COMMENT["brand"]


class Draft(BaseModel):
    scene: str = Field(description="댓글이 짚은 영상 속 장면이나 말")
    nudge_style: Literal["소문", "질문", "다짐"] = Field(description="운명원을 꺼낸 방식")
    text: str = Field(description="댓글 본문")


SYSTEM = f"""너는 방금 이 영상을 본 시청자야. 주어진 페르소나 그 자체로 유튜브 댓글 하나를 써.

제품 정보: {BRAND}은 연애사주·궁합을 잘 봐주기로 유명한 곳이야. 읽는 사람이 {BRAND}이 뭘 하는 곳인지 알 수 있게 '연애사주'나 '궁합' 중 한 단어를 자연스럽게 붙여.

담을 것 세 가지 (순서와 비중은 자유, 매번 다른 구조로):
- 영상 속 구체적 장면이나 말 하나 (다른 영상에는 붙일 수 없는 디테일)
- 페르소나의 처지와 감정 (journey의 일상 디테일 활용)
- {BRAND}을 꺼내는 방식 하나를 골라:
  소문: "~ 잘 본다던데", "~ 유명하다더라" 처럼 들은 얘기
  질문: "{BRAND} 연애사주 본 사람 있어요?" 처럼 다른 시청자에게 묻기
  다짐: "이번 주말에 {BRAND} 궁합이라도 볼까" 처럼 앞으로의 계획

규칙:
- {COMMENT['min_chars']}~{COMMENT['max_chars']}자 (공백 포함)
- 링크, 해시태그 금지
- {BRAND}을 직접 이용해 본 것처럼 쓰는 후기 금지 (가봤다, 받아봤다, 용하더라, 맞더라 등)
- 광고처럼 보이면 실패. 페르소나 말투(voice)를 따라
- recent_comments와 시작 방식, 문장 구조, 끝맺음, {BRAND} 꺼내는 방식이 겹치지 않게
- transcript_used가 false면 key_scenes는 제목·설명 요약이라 실제 대사가 아니야. 따옴표로 인용하지 말고 풀어서 언급해"""


def run(video: dict, p: PersonaResult, j: Journey, transcript_used: bool,
        recent: list[str] | None = None, feedback: str | None = None) -> Draft:
    body = {
        "video_title": video["title"],
        "transcript_used": transcript_used,
        "key_scenes": p.key_scenes,
        "persona": p.persona.model_dump(),
        "journey": j.model_dump(exclude={"sources"}),
        "recent_comments": recent or [],
    }
    if feedback:
        body["fix_previous"] = feedback
    return ask(SYSTEM, json.dumps(body, ensure_ascii=False), Draft)
