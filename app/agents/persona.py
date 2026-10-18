"""Agent 1. 페르소나 분석가: 가짜 댓글을 거르고, 진짜 시청자 목소리에서 고민과 페르소나를 뽑아요."""
import json
from typing import Literal

from pydantic import BaseModel, Field

from ..llm import ask


class Filtered(BaseModel):
    text: str
    reason: str = Field(description="광고/브랜드 언급, 복붙형, 영상 내용 없는 칭찬, 부자연스러운 반응 등")


class Persona(BaseModel):
    label: str = Field(description="짧은 이름. 예: 썸 타다 읽씹당한 20대 후반 직장인")
    situation: str = Field(description="지금 어떤 연애 상황에 있는지")
    emotions: list[str] = Field(description="두드러지는 감정 단어 3~5개")
    voice: str = Field(description="말투 특징. 예: 반말, ㅠㅠ 자주, 자조적 유머")


class PersonaResult(BaseModel):
    worry: str = Field(description="영상이 다루는 연애 고민 한 줄")
    key_scenes: list[str] = Field(description="영상 속 구체적인 장면이나 말 2~4개")
    filtered: list[Filtered]
    evidence: list[str] = Field(description="페르소나 근거가 된 진짜 시청자 댓글 원문 (최대 5개, 고민과 무관한 댓글은 넣지 말 것)")
    confidence: Literal["높음", "낮음"] = Field(description="고민과 관련된 진짜 댓글이 3개 이상이면 높음, 아니면 낮음")
    persona: Persona


SYSTEM = """너는 연애 콘텐츠 시청자 리서처야.
1) 댓글 중 진짜 시청자가 아닐 가능성이 높은 것(업체·브랜드 홍보, 다른 영상에도 붙을 법한 복붙 문장, 영상 내용 없는 칭찬, 좋아요 대비 부자연스러운 반응)을 걸러내.
2) 남은 진짜 댓글과 영상 내용으로, 이 영상이 다루는 연애 고민을 한 줄로 정리하고, 댓글에서 가장 두드러지는 시청자 페르소나 하나를 뽑아.
3) 영상 속 구체적인 장면이나 화자의 말을 key_scenes로 뽑아. 자막에 실제로 있는 말만 인용하고, 자막이 없으면 제목·설명에 적힌 내용을 요약해(대사를 지어내지 마).
4) 근거 댓글이 부족하면 영상 내용으로 페르소나를 보강하되 confidence를 낮음으로 표시해."""


def run(video: dict, transcript: str | None, comments: list[dict]) -> PersonaResult:
    body = {
        "title": video["title"],
        "channel": video["channel_title"],
        "description": video.get("description", "")[:2000],
        "transcript": (transcript or "(자막 없음)")[:15000],
        "comments": comments,
    }
    return ask(SYSTEM, json.dumps(body, ensure_ascii=False), PersonaResult)
