"""카테고리 이름 규칙."""

MAX_CATEGORY_NAME_LENGTH = 40


class CategoryInputError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def validate_category_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise CategoryInputError("이름이 필요함")
    if len(cleaned) > MAX_CATEGORY_NAME_LENGTH:
        raise CategoryInputError(f"이름은 {MAX_CATEGORY_NAME_LENGTH}자까지")
    return cleaned
