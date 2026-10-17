"""Discord 메시지 만들기. 길이가 넘쳐도 머리말, 제목, 서비스 글 링크는 남긴다."""

from datetime import datetime, tzinfo

from rss_hub.domain.text import truncate_with_ellipsis

MAX_MESSAGE_LENGTH = 1900  # Discord 한도(2000자)보다 여유를 둔다
MAX_TITLE_LENGTH = 300
LINK_LABEL = "글 읽기"


def article_url(base_url: str, article_id: int) -> str:
    """서비스 글 주소. base_url은 끝 슬래시가 없는 정규화된 값이다."""
    return f"{base_url}/a/{article_id}"


def format_published_time(published: str | datetime | None, tz: tzinfo) -> str | None:
    """발행 시각을 서비스 시간대의 "HH:MM"으로. 알 수 없으면 None."""
    if not published:
        return None
    if isinstance(published, datetime):
        moment = published
    else:
        try:
            moment = datetime.fromisoformat(published)
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return moment.astimezone(tz).strftime("%H:%M")


def build_message(
    *,
    site: str,
    emoji: str,
    title: str,
    summary: str,
    published: str | datetime | None,
    link_url: str,
    tz: tzinfo,
    max_length: int = MAX_MESSAGE_LENGTH,
) -> str:
    """머리말, 제목, 요약, 서비스 글 링크로 메시지를 만든다. 길면 요약을 줄여서 링크를 지킨다."""
    time_text = format_published_time(published, tz)
    header = f"{emoji} **[{site}] 새 글 알림**" + (f" `{time_text}`" if time_text else "")
    title_line = f"**{truncate_with_ellipsis(title, MAX_TITLE_LENGTH)}**"
    link_line = f"🔗 [{LINK_LABEL}]({link_url})"

    fixed_length = len("\n".join([header, title_line, "", link_line]))  # 요약 줄은 빈 줄로 계산
    summary_budget = max_length - fixed_length
    summary_text = truncate_with_ellipsis(summary, summary_budget)

    lines = [header, title_line]
    if summary_text:
        lines.append(summary_text)
    lines.append(link_line)
    return "\n".join(lines)
