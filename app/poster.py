"""③ 댓글 달기. 에이전트가 아니라 정해진 순서대로만 움직이는 코드예요.

크롬은 평소 쓰는 기본 프로필의 자동 제어를 막아서, data/profiles/<프로필> 폴더를 따로 만들어 씁니다.
처음 한 번은 `python -m app.poster login 유튜브1`로 일반 크롬 창을 열어 구글 로그인을 하고,
아무 영상에나 댓글을 한 번 손으로 달아 두세요(새 계정의 "채널 만들기" 팝업을 미리 넘기기 위해서예요).

상태: queued → opening → typing → submitted → posted
      submitted 이후에 실패하면 unverified(올라갔을 수도 있음). 사람이 확인할 때까지 그 영상은 막아 둬요.
"""
import os
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import db
from .config import CONFIG, PROFILES_DIR, SCREENSHOTS_DIR

# 한 번에 하나만 게시해요. 규칙 검사와 기록 사이의 경합, 같은 프로필 중복 실행을 함께 막아요.
POST_LOCK = threading.Lock()

STAGE_REASON = {
    "opening": "크롬 프로필을 열지 못했어요",
    "comments": "댓글 입력창을 찾지 못했어요 (로그인 안 됨, 채널 만들기 필요, 또는 댓글 사용 중지 영상)",
    "typing": "댓글을 입력하다 멈췄어요",
    "verify": "게시 버튼은 눌렀지만 내 댓글을 목록에서 확인하지 못했어요. 영상에서 직접 확인해 주세요",
}


def _set(post_id: int, status: str, **extra):
    sets = ", ".join(["status=?", "updated_at=datetime('now','localtime')", *(f"{k}=?" for k in extra)])
    with db.tx() as c:
        # 한 번 posted가 된 기록은 덮어쓰지 않아요
        c.execute(f"UPDATE posts SET {sets} WHERE id=? AND status!='posted'", (status, *extra.values(), post_id))


def _reason(stage: str, e: Exception) -> str:
    msg = str(e)
    if any(k in msg for k in ("already in use", "ProcessSingleton", "user data directory")):
        return "이 프로필의 크롬 창이 이미 열려 있어요. 창을 닫고 다시 시도해 주세요."
    if "has been closed" in msg:
        return "게시 도중 크롬 창이 닫혔어요."
    return f"{STAGE_REASON.get(stage, '알 수 없는 오류')} ({type(e).__name__})"


def _match_key(text: str) -> str:
    """내 댓글을 목록에서 찾을 때 쓸 고유 구간. 이모지·기호를 피해 가장 긴 한글/영문 구간의 뒤쪽을 써요."""
    runs = re.findall(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9 ,]*", text)
    best = max(runs, key=len).strip() if runs else text.strip()
    return best[-16:].strip()


def _open(p, profile: str):
    win = CONFIG.get("poster_window")
    if win:  # 창 위치를 정해 두면 시연 녹화 때 대시보드 ③ 칸과 나란히 보여요
        size = {"args": [f"--window-position={win['x']},{win['y']}", f"--window-size={win['width']},{win['height']}"],
                "no_viewport": True}
    else:
        size = {"viewport": {"width": 1280, "height": 900}}
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILES_DIR / profile),
        channel="chrome",
        headless=False,
        locale="ko-KR",
        **size,
    )


def _shot(page, name: str) -> str | None:
    try:
        path = SCREENSHOTS_DIR / name
        page.screenshot(path=str(path))
        return path.name
    except Exception:
        return None


def _post(post_id: int, video_id: str, profile: str, text: str):
    stage, submitted = "opening", False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ctx = page = None
            try:
                _set(post_id, "opening")
                ctx = _open(p, profile)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                # 계정 언어와 상관없이 한국어 유튜브 화면으로 열어요 (셀렉터는 언어와 무관한 ID라 동작은 같아요)
                page.goto(f"https://www.youtube.com/watch?v={video_id}&hl=ko&persist_hl=1", wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                stage = "comments"
                # 댓글 영역은 스크롤해야 불러와져요
                for _ in range(8):
                    page.mouse.wheel(0, 600)
                    page.wait_for_timeout(700)
                    if page.locator("#simplebox-placeholder").count():
                        break
                page.locator("#simplebox-placeholder").click(timeout=15000)

                stage = "typing"
                _set(post_id, "typing")
                page.locator("#contenteditable-root").click()
                for ch in text:  # 한 글자씩, 사람 속도로
                    page.keyboard.type(ch)
                    time.sleep(random.uniform(0.05, 0.16))
                page.wait_for_timeout(800)

                # 클릭 이후의 실패는 "실패"가 아니라 "확인 필요"예요. 이미 올라갔을 수 있어서요.
                stage = "verify"
                _set(post_id, "submitted")
                submitted = True
                page.locator("ytd-comment-simplebox-renderer #submit-button").click()

                key = _match_key(text)
                mine = page.locator("ytd-comment-thread-renderer").filter(
                    has=page.locator("#content-text", has_text=key)).first
                mine.wait_for(timeout=20000)
                mine.scroll_into_view_if_needed()

                href = mine.locator("#published-time-text a").first.get_attribute("href", timeout=5000)
                url = ("https://www.youtube.com" + href) if href and href.startswith("/") else \
                    f"https://www.youtube.com/watch?v={video_id}"
                page.wait_for_timeout(1000)
                _set(post_id, "posted", screenshot=_shot(page, f"post-{post_id}-ok.png"), comment_url=url, error=None)
                page.wait_for_timeout(2500)  # 시연 화면에서 결과를 잠깐 보여줘요
            except Exception as e:
                shot = _shot(page, f"post-{post_id}-fail.png") if page else None
                _set(post_id, "unverified" if submitted else "failed", error=_reason(stage, e), screenshot=shot)
            finally:
                if ctx:
                    try:
                        ctx.close()
                    except Exception:
                        pass
    except Exception as e:
        _set(post_id, "unverified" if submitted else "failed", error=_reason(stage, e))
    finally:
        POST_LOCK.release()


def start(post_id: int, video_id: str, profile: str, text: str):
    """호출 전에 POST_LOCK을 잡아 둬야 해요. 스레드가 끝날 때 풀어요."""
    threading.Thread(target=_post, args=(post_id, video_id, profile, text), daemon=True).start()


def _chrome_path() -> str | None:
    for base in (os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"), os.getenv("LOCALAPPDATA")):
        if base and (p := Path(base) / "Google/Chrome/Application/chrome.exe").exists():
            return str(p)
    return None


def login(profile: str):
    """프로필 폴더에 구글 로그인을 해 두는 1회용 도우미.

    자동화 표시가 붙은 창에서는 구글이 로그인을 막을 수 있어서, 같은 프로필 폴더로 일반 크롬을 열어요.
    """
    chrome = _chrome_path()
    if not chrome:
        sys.exit("크롬을 찾지 못했어요. 크롬을 설치해 주세요.")
    folder = PROFILES_DIR / profile
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([chrome, f"--user-data-dir={folder}", "--no-first-run",
                      "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://www.youtube.com"])
    print(f"[{profile}] 열린 크롬 창에서 로그인하고, 아무 영상에 댓글을 한 번 달아 둔 뒤 창을 닫으세요.")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "login":
        login(sys.argv[2])
    else:
        print("사용법: python -m app.poster login 유튜브1")
