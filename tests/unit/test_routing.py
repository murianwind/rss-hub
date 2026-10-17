import pytest

from rss_hub.domain.routing import PRIMARY, Target, resolve_targets, topic_purpose


def targets(*, feed=None, category=None, default=1, topics=()):
    return resolve_targets(
        feed_webhook_id=feed,
        category_webhook_id=category,
        default_webhook_id=default,
        topic_webhooks=topics,
    )


def test_the_default_webhook_is_used_when_the_category_has_none():
    assert targets() == (Target(1, PRIMARY),)


def test_the_category_webhook_wins_over_the_default():
    assert targets(category=2) == (Target(2, PRIMARY),)


def test_without_any_primary_webhook_nothing_is_sent():
    assert targets(default=None) == ()


def test_topic_webhooks_do_not_replace_a_missing_primary():
    assert targets(default=None, topics=[(7, 3)]) == ()


def test_a_topic_webhook_is_added_after_the_primary():
    assert targets(topics=[(7, 3)]) == (Target(1, PRIMARY), Target(3, topic_purpose(7)))


def test_a_topic_whose_webhook_equals_the_primary_adds_nothing():
    assert targets(topics=[(7, 1)]) == (Target(1, PRIMARY),)
    assert targets(category=2, topics=[(7, 2)]) == (Target(2, PRIMARY),)


def test_a_topic_may_use_the_default_webhook_when_the_category_has_its_own():
    assert targets(category=2, topics=[(7, 1)]) == (Target(2, PRIMARY), Target(1, topic_purpose(7)))


def test_two_topics_sharing_a_webhook_send_once_for_the_first_topic():
    assert targets(topics=[(7, 3), (8, 3)]) == (Target(1, PRIMARY), Target(3, topic_purpose(7)))


def test_different_topic_webhooks_each_get_a_message_in_order():
    assert targets(topics=[(8, 4), (7, 3)]) == (
        Target(1, PRIMARY),
        Target(4, topic_purpose(8)),
        Target(3, topic_purpose(7)),
    )


def test_a_topic_without_a_webhook_adds_nothing():
    assert targets(topics=[(7, None)]) == (Target(1, PRIMARY),)


@pytest.mark.parametrize("topic_id", [1, 42])
def test_the_purpose_names_the_topic(topic_id):
    assert topic_purpose(topic_id) == f"topic:{topic_id}"


def test_the_feed_webhook_wins_over_the_category_and_the_default():
    assert targets(feed=5, category=2) == (Target(5, PRIMARY),)
    assert targets(feed=5) == (Target(5, PRIMARY),)


def test_a_feed_webhook_is_enough_even_without_a_default_webhook():
    assert targets(feed=5, default=None) == (Target(5, PRIMARY),)


def test_a_topic_article_from_a_feed_with_its_own_webhook_does_not_go_to_the_default():
    assert targets(feed=5, topics=[(7, 3)]) == (Target(5, PRIMARY), Target(3, topic_purpose(7)))


def test_a_topic_webhook_equal_to_the_feed_webhook_adds_nothing():
    assert targets(feed=5, topics=[(7, 5)]) == (Target(5, PRIMARY),)
