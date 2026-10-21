"""양식 값을 읽는 공통 규칙."""


def id_or_none(value: object) -> int | None:
    """양식의 번호 칸. 비었거나 숫자가 아니면 None(지정 안 함)으로 본다."""
    text = str(value or "").strip()
    # isdigit()은 "²" 같은 위첨자도 참이라 int()가 예외를 내므로 isdecimal()로 가른다
    return int(text) if text.isdecimal() else None
