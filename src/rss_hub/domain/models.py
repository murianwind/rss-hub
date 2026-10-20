"""OpenRouter 모델 목록에서 무료이고 텍스트만 출력하는 모델을 골라낸다."""

from dataclasses import dataclass

MIN_CONTEXT = 8192  # 요약에 쓰기에는 이보다 작은 문맥은 부족하다


@dataclass(frozen=True)
class FreeModel:
    id: str
    name: str
    context_length: int
    supports_json: bool  # response_format 지원
    supports_reasoning: bool  # reasoning 옵션 지원(추론 끄기에 쓴다)


def _is_zero(value: object) -> bool:
    try:
        return float(value) == 0.0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _free(item: dict[str, object]) -> FreeModel | None:
    model_id = item.get("id")
    pricing = item.get("pricing")
    if not isinstance(model_id, str) or not isinstance(pricing, dict):
        return None
    if not (_is_zero(pricing.get("prompt")) and _is_zero(pricing.get("completion"))):
        return None
    architecture = item.get("architecture")
    outputs = architecture.get("output_modalities") if isinstance(architecture, dict) else None
    if isinstance(outputs, list) and set(outputs) != {"text"}:
        return None  # 이미지나 음악 같은 것도 만들어 내는 모델은 요약에 쓰지 않는다
    context = item.get("context_length")
    if not isinstance(context, int) or context < MIN_CONTEXT:
        return None
    raw_params = item.get("supported_parameters")
    params = set(raw_params) if isinstance(raw_params, list) else set()
    name = item.get("name")
    return FreeModel(
        id=model_id,
        name=name if isinstance(name, str) and name else model_id,
        context_length=context,
        supports_json="response_format" in params,
        supports_reasoning="reasoning" in params,
    )


def parse_free_models(payload: object) -> list[FreeModel]:
    """/models 응답에서 무료이고 텍스트를 내놓는 모델(id 순서, 중복 없이)."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    found: dict[str, FreeModel] = {}
    for item in data:
        model = _free(item) if isinstance(item, dict) else None
        if model is not None:
            found.setdefault(model.id, model)
    return [found[key] for key in sorted(found)]
