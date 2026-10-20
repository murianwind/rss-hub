import pytest

from rss_hub.domain.topics import TopicFields
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository, FeedRuleError
from rss_hub.storage.ordering import OrderRepository
from rss_hub.storage.reader import ReaderRepository
from rss_hub.storage.topics import TopicRepository
from tests.fakes.clock import FakeClock


@pytest.fixture
def env(tmp_path):
    db, clock = Database(tmp_path / "rss_hub.db"), FakeClock()
    feeds, topics = FeedRepository(db, clock), TopicRepository(db, clock)
    a, b, c = (feeds.add(f"https://{n}.example.com/rss", n) for n in ("가", "나", "다"))
    return db, feeds, topics, OrderRepository(db), ReaderRepository(db, clock), (a, b, c)


def test_a_saved_order_decides_the_sidebar_order(env):
    _, _, _, orders, reader, (a, b, c) = env
    assert [f.id for f in reader.sidebar().feeds] == [a, b, c]  # 저장한 순서가 없으면 이름순
    assert orders.set_order("feed", [c, a, b]) is True
    assert [f.id for f in reader.sidebar().feeds] == [c, a, b]


def test_categories_and_topics_can_be_ordered_too(env):
    _, feeds, topics, orders, reader, _ = env
    first, second = feeds.add_category("가"), feeds.add_category("나")
    t1 = topics.add(TopicFields("가주제", "", ()))
    t2 = topics.add(TopicFields("나주제", "", ()))
    assert orders.set_order("category", [second, first]) and orders.set_order("topic", [t2, t1])
    side = reader.sidebar()
    assert [c.id for c in side.categories] == [second, first]
    assert [t.id for t in side.topics if t.id in (t1, t2)] == [t2, t1]


@pytest.mark.parametrize("kind", ["", "articles", "feed; DROP TABLE feeds", "FEED"])
def test_an_unknown_kind_changes_nothing(env, kind):
    _, _, _, orders, reader, (a, b, c) = env
    assert orders.set_order(kind, [c, b, a]) is False
    assert [f.id for f in reader.sidebar().feeds] == [a, b, c]


def test_a_bad_list_changes_nothing(env):
    _, _, _, orders, reader, (a, b, c) = env
    assert orders.set_order("feed", []) is False
    assert orders.set_order("feed", [c, 999]) is False  # 없는 번호
    assert orders.set_order("feed", [c, c, b]) is False  # 중복
    assert [f.id for f in reader.sidebar().feeds] == [a, b, c]


def test_only_the_listed_items_are_renumbered_and_the_rest_keep_their_place(env):
    _, _, _, orders, reader, (a, b, c) = env
    orders.set_order("feed", [c, b])
    assert [f.id for f in reader.sidebar().feeds][:3] == [a, c, b]  # a는 0이라 앞에 남는다


def test_renaming_a_category_checks_for_duplicates(env):
    _, feeds, _, _, _, _ = env
    first, second = feeds.add_category("뉴스"), feeds.add_category("기술")
    assert feeds.rename_category(first, "소식") is True
    assert {c.name for c in feeds.list_categories()} == {"소식", "기술"}
    with pytest.raises(FeedRuleError, match="같은 이름"):
        feeds.rename_category(second, "소식")
    assert feeds.rename_category(999, "x") is False


def test_deleting_a_category_keeps_its_feeds_without_a_category(env):
    _, feeds, _, _, _, (a, _, _) = env
    category = feeds.add_category("뉴스")
    feeds.set_feed_category(a, category)
    assert feeds.delete_category(category) is True
    assert feeds.get(a) is not None and feeds.get(a).category_id is None
    assert feeds.delete_category(category) is False
