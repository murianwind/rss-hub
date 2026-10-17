"""가져오기 테스트 환경: 수집 환경(CollectEnv)에 임시 보관 저장소와 가져오기 서비스를 더한다."""

from rss_hub.services.importer import ImportService
from rss_hub.storage.import_staging import ImportStagingRepository
from tests.fakes.collect_env import CollectEnv


class ImportEnv(CollectEnv):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.staging = ImportStagingRepository(self.db, self.clock)
        self.importer = ImportService(feeds=self.feeds, staging=self.staging, clock=self.clock)
        # 배경: 구독 목록에 이미 있는 피드 두 개
        self.feeds.add("https://a.example.com/feed", "A")
        self.feeds.add("https://b.example.com/rss", "B")

    def feed_count(self) -> int:
        return len(self.feeds.list_all())
