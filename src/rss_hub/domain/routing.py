"""발송 대상 결정: 피드, 카테고리, 기본 웹훅 중 첫 지정값 하나에 해당 주제들의 웹훅을 더한다."""

from collections.abc import Sequence
from dataclasses import dataclass

PRIMARY = "primary"


def topic_purpose(topic_id: int) -> str:
    return f"topic:{topic_id}"


@dataclass(frozen=True)
class Target:
    webhook_id: int
    purpose: str  # PRIMARY 또는 topic_purpose(주제 번호)


def resolve_targets(
    *,
    feed_webhook_id: int | None,
    category_webhook_id: int | None,
    default_webhook_id: int | None,
    topic_webhooks: Sequence[tuple[int, int | None]],
) -> tuple[Target, ...]:
    """글 하나의 발송 대상. 기본 대상을 정할 수 없으면 빈 튜플(발송 보류)을 돌려준다.

    topic_webhooks는 글이 해당한 주제의 (주제 번호, 웹훅 번호) 목록이다.
    피드나 카테고리 웹훅으로 가는 피드의 주제 글도 기본 웹훅으로는 가지 않는다.
    같은 웹훅으로는 메시지를 한 번만 보낸다(기본 대상과 같거나 다른 주제와 같은 경우).
    """
    # 피드 웹훅은 카테고리에 속하지 않은 피드에만 지정할 수 있다(저장소가 지킨다)
    primary = next(
        (w for w in (feed_webhook_id, category_webhook_id, default_webhook_id) if w is not None),
        None,
    )
    if primary is None:
        return ()
    targets = [Target(primary, PRIMARY)]
    used = {primary}
    for topic_id, webhook_id in topic_webhooks:
        if webhook_id is None or webhook_id in used:
            continue
        used.add(webhook_id)
        targets.append(Target(webhook_id, topic_purpose(topic_id)))
    return tuple(targets)
