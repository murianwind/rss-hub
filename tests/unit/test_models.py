import pytest

from rss_hub.domain.models import MIN_CONTEXT, parse_free_models


def item(
    model_id="a/free-model:free",
    *,
    prompt="0",
    completion="0",
    context=32768,
    outputs=None,
    params=None,
    name=None,
):
    data = {
        "id": model_id,
        "name": name or model_id,
        "context_length": context,
        "pricing": {"prompt": prompt, "completion": completion},
        "architecture": {"output_modalities": outputs or ["text"]},
        "supported_parameters": params or [],
    }
    return data


def parse(*items):
    return parse_free_models({"data": list(items)})


def test_free_text_models_are_listed_with_their_abilities():
    found = parse(item(params=["response_format", "reasoning", "temperature"], name="Free Model"))
    assert [
        (m.id, m.name, m.context_length, m.supports_json, m.supports_reasoning) for m in found
    ] == [("a/free-model:free", "Free Model", 32768, True, True)]


def test_a_model_without_json_or_reasoning_support_says_so():
    (model,) = parse(item(params=["temperature"]))
    assert (model.supports_json, model.supports_reasoning) == (False, False)


@pytest.mark.parametrize(
    ("prompt", "completion"),
    [("0.000001", "0"), ("0", "0.000002"), ("-1", "-1"), (None, "0"), ("abc", "0")],
)
def test_models_that_cost_anything_or_have_unclear_prices_are_not_free(prompt, completion):
    assert parse(item(prompt=prompt, completion=completion)) == []


@pytest.mark.parametrize("zero", ["0", 0, 0.0, "0.0", "0.00000"])
def test_zero_prices_in_any_notation_count_as_free(zero):
    assert len(parse(item(prompt=zero, completion=zero))) == 1


@pytest.mark.parametrize(
    "outputs",
    [["image"], ["audio"], ["text", "image"], ["text", "audio"], ["text", "audio", "image"], []],
)
def test_models_that_produce_anything_but_text_are_skipped(outputs):
    # 음악이나 이미지를 만들어 내는 모델은 요약에 쓸 수 없다(실제 목록에 text+audio 모델이 있었다)
    assert parse(item(outputs=outputs)) == [] or outputs == []


def test_a_model_that_outputs_only_text_is_kept_and_a_missing_modality_list_is_tolerated():
    assert len(parse(item(outputs=["text"]))) == 1
    (model,) = parse_free_models(
        {
            "data": [
                {
                    "id": "a/b:free",
                    "context_length": 16384,
                    "pricing": {"prompt": "0", "completion": "0"},
                }
            ]
        }
    )
    assert model.id == "a/b:free"


def test_models_with_a_small_context_are_skipped():
    assert parse(item(context=MIN_CONTEXT - 1)) == []
    assert len(parse(item(context=MIN_CONTEXT))) == 1
    assert parse(item(context=None)) == []


def test_the_list_is_sorted_by_id_and_has_no_duplicates():
    found = parse(item("b/model:free"), item("a/model:free"), item("b/model:free"))
    assert [m.id for m in found] == ["a/model:free", "b/model:free"]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "x",
        {},
        {"data": None},
        {"data": "x"},
        {"data": [None, 1, "x", {}, {"id": 5}]},
        {"data": [{"id": "a/b", "pricing": "free"}]},
    ],
)
def test_unusable_payloads_give_an_empty_list_without_raising(payload):
    assert parse_free_models(payload) == []


def test_missing_optional_fields_are_tolerated():
    (model,) = parse_free_models(
        {
            "data": [
                {
                    "id": "a/b:free",
                    "context_length": 16384,
                    "pricing": {"prompt": "0", "completion": "0"},
                }
            ]
        }
    )
    assert (model.name, model.supports_json) == ("a/b:free", False)
