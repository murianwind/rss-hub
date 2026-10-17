#!/usr/bin/env python3
"""레거시 RSS 스크립트의 순수 함수를 실제로 실행해 골든 데이터를 만든다.

목적
  - 새 서비스가 "기존 동작을 유지"하는지(parity)와 "의도적으로 바꾼" 부분(known_defects)을
    테스트가 기계적으로 구분할 수 있게 한다.

사용법 (Linux/Docker에서 실행; Windows는 time.tzset이 없어 시간대 고정이 불가능하다)
  python tools/generate_legacy_golden.py --legacy-dir ./legacy --out tests/golden/legacy_golden.json

레거시 스크립트 7개를 --legacy-dir에 두고 실행한다. 결과 JSON은 저장소에 커밋하고,
레거시 코드가 바뀌지 않는 한 다시 만들 필요가 없다.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

TZ = "Asia/Seoul"
TARGET_DATE = "2026-10-16"


def _pin_environment() -> None:
    os.environ["TZ"] = TZ
    os.environ["RSS_TARGET_DATE"] = TARGET_DATE
    if not hasattr(time, "tzset"):
        raise SystemExit("time.tzset을 쓸 수 없는 환경입니다. Linux/Docker에서 실행하세요.")
    time.tzset()


def _struct(parts):
    return time.struct_time(tuple(parts))


def build_golden(legacy_dir: Path) -> dict:
    sys.path.insert(0, str(legacy_dir))
    import rss_collector as collector
    import rss_reporter as reporter
    import rss_translator as translator

    golden: dict = {
        "meta": {
            "tz": TZ,
            "target_date": TARGET_DATE,
            "legacy_files": sorted(p.name for p in legacy_dir.glob("rss_*.py")),
            "how_to_read": {
                "parity": "새 구현이 같은 입력에 같은 결과를 내야 한다.",
                "known_defects": "레거시가 틀린 케이스. 새 구현은 new_expected를 따라야 한다.",
                "invariants": "정확한 값이 아니라 만족해야 하는 성질.",
            },
        }
    }

    # --- GUID 정규화 -------------------------------------------------
    guid_inputs = [
        "https://blog.naver.com/abc/123?fromRss=true&trackingCode=rss",
        "https://blog.naver.com/abc/123?fromRss=true&trackingCode=rss&x=1",
        "https://example.com/p?a=1&a=2",
        "https://example.com/p?q=hello world&z=%EA%B0%80",
        "https://gizmodo.com/?p=123",
        "tag:example.com,2026:post-1",
        "urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a",
        "https://example.com/post#frag",
        "https://example.com/p?empty=&k=v",
        "",
        None,
    ]
    golden["normalize_guid"] = {
        "parity": [{"input": g, "expected": collector.normalize_guid(g)} for g in guid_inputs],
        "idempotent_for_all_inputs": all(
            collector.normalize_guid(collector.normalize_guid(g)) == collector.normalize_guid(g)
            for g in guid_inputs
        ),
    }

    # --- GUID 선택 우선순위 -----------------------------------------
    entries = [
        {"id": "https://x.com/a?trackingCode=1"},
        {"guid": "g1"},
        {"link": "https://x.com/l?fromRss=true"},
        {"title": "t", "summary": "s"},
    ]
    golden["guid_for"] = {
        "parity": [{"entry": e, "expected": collector.guid_for(e)} for e in entries]
    }

    # --- 발행 시각 파싱 ----------------------------------------------
    dt_cases = [
        {"published_parsed": [2026, 10, 15, 16, 30, 0, 0, 0, 0]},
        {"updated_parsed": [2026, 10, 16, 0, 5, 0, 0, 0, 0]},
        {"published": "Fri, 16 Oct 2026 01:30:00 +0900"},
        {"published": "Fri, 16 Oct 2026 01:30:00 GMT"},
        {"published": "2026-10-16T01:30:00Z"},
        {"published": "2026-10-16T01:30:00"},
        {"published": "Fri, 16 Oct 2026 01:30:00"},
        {"published": "not a date"},
        {},
    ]
    dt_rows = []
    for case in dt_cases:
        entry = {k: (_struct(v) if k.endswith("_parsed") else v) for k, v in case.items()}
        parsed = collector.parsed_entry_datetime(entry)
        dt_rows.append(
            {
                "entry": case,
                "expected_iso": parsed.isoformat() if parsed else None,
                "expected_date": parsed.date().isoformat() if parsed else None,
            }
        )
    golden["parsed_entry_datetime"] = {"parity": dt_rows}

    # --- 한국어 판별 (한글 비율 >= 0.1) -------------------------------
    korean_texts = [
        "",
        "<p></p>",
        "hello world",
        "안녕 hello world this is a long english sentence okay",
        "가" + "a" * 8,
        "가" + "a" * 9,
        "가" + "a" * 10,
    ]
    golden["is_korean"] = {
        "parity": [{"text": t, "expected": translator.is_korean(t)} for t in korean_texts]
    }

    # --- 재요약 필요 여부 (이전 데이터 해석용) ------------------------
    retrans_items = [
        {},
        {"translated": "ok", "translated_model": "openrouter/x"},
        {"translated": "ok", "translated_model": "fallback"},
        {"translated": "ok", "translated_model": "fallback-final"},
        {"translated": "TITLE: x"},
        {"translated": "We need to translate this"},
        {"translated": "漢字 포함", "translated_model": "m"},
        {"translated": "good", "translated_model": "korean-summary"},
    ]
    golden["needs_retranslation"] = {
        "parity": [
            {"item": i, "expected": translator.needs_retranslation(i)} for i in retrans_items
        ]
    }

    # --- 활동량별 점검 횟수 ------------------------------------------
    activity = [(0, 0), (0, 2), (0, 6), (1, 1), (2, 0), (0, 7), (3, 0)]
    rows = []
    for today, week in activity:
        stats = {"u": {"recent_count_7d": week, "target_date_count": today}}
        feed = {"url": "u", "name": "u"}
        rows.append(
            {
                "target_date_count": today,
                "recent_count_7d": week,
                "expected_checks": collector.desired_checks_per_hour(feed, stats),
                "expected_score": collector.feed_activity_score(feed, stats),
            }
        )
    golden["desired_checks_per_hour"] = {"parity": rows}

    # --- 슬롯 번호 ----------------------------------------------------
    golden["current_slot"] = {
        "parity": [
            {
                "minute": m,
                "expected": collector.current_slot(datetime(2026, 10, 16, 14, m, 0).astimezone()),
            }
            for m in (0, 4, 5, 59)
        ]
    }

    # --- 스케줄 성질 (정확한 배치가 아닌 불변식) -----------------------
    now = datetime(2026, 10, 16, 14, 32, 0).astimezone()
    feeds = [{"name": f"feed{i:03d}", "url": f"https://ex{i}.com/rss"} for i in range(134)]
    schedule = collector.build_hourly_schedule(feeds, {}, now)
    sizes = [len(b) for b in schedule["batches"]]
    golden["schedule"] = {
        "invariants": {
            "feeds": 134,
            "runs_per_hour": schedule["runs_per_hour"],
            "batch_size": schedule["batch_size"],
            "capacity": schedule["capacity"],
            "every_feed_covered_at_least_once": len(
                {f["url"] for b in schedule["batches"] for f in b}
            )
            == 134,
            "max_slot_size": max(sizes),
        },
        "batch_size_for_200_feeds": collector.build_hourly_schedule(
            [{"name": f"m{i}", "url": f"https://m{i}.com/rss"} for i in range(200)], {}, now
        )["batch_size"],
    }

    # --- 알려진 결함: every-slot 피드가 보장되지 않음 -----------------
    aw = "https://awesome-blogs.petabytes.org/feed.xml"

    def slots_with(feed_url, sched):
        return sum(1 for b in sched["batches"] if any(f["url"] == feed_url for f in b))

    mixed = [{"name": f"feed{i:03d}", "url": f"https://ex{i}.com/rss"} for i in range(133)]
    mixed.append({"name": "awesome", "url": aw})
    strong = {f["url"]: {"recent_count_7d": 30, "target_date_count": 30} for f in mixed}
    strong[aw] = {"recent_count_7d": 50, "target_date_count": 10}
    golden["schedule"]["known_defects"] = [
        {
            "case": "통계가 없는 첫 실행",
            "legacy_slots_for_every_slot_feed": slots_with(
                aw, collector.build_hourly_schedule(mixed, {}, now)
            ),
            "new_expected_slots": 12,
        },
        {
            "case": "다른 피드의 활동 점수가 더 높음",
            "legacy_slots_for_every_slot_feed": slots_with(
                aw, collector.build_hourly_schedule(mixed, strong, now)
            ),
            "new_expected_slots": 12,
        },
    ]

    # --- OTT 2차 키워드 검증 -----------------------------------------
    def gate(title, content="", is_ott=True):
        return reporter.is_ott_related({"is_ott": is_ott, "title": title, "content": content})

    parity_cases = [
        ("New Netflix drama", "", True),
        ("Apple event recap", "", True),
        ("스트리밍 서비스 요금", "", True),
        ("movie night", "", True),
        ("filmmaker interview", "", True),
        ("seasoning tips", "", True),
        ("Season finale", "", True),
        ("New Netflix drama", "", False),
        ("New Netflix drama", "", None),
    ]
    golden["ott_gate"] = {
        "parity": [
            {"title": t, "content": c, "is_ott": o, "expected": gate(t, c, o)}
            for t, c, o in parity_cases
        ],
        "known_defects": [
            {
                "case": "영문 약어 'ott'가 단어 안에서도 일치(부분 문자열)",
                "title": t,
                "legacy": gate(t),
                "new_expected": False,
            }
            for t in ("A bottle of water", "Lotto results", "gotta love it")
        ]
        + [
            {
                "case": "'+'로 끝나는 키워드: 공백이 뒤따르면 불일치, 글자가 붙으면 오일치",
                "title": t,
                "legacy": gate(t),
                "new_expected": expected,
            }
            for t, expected in (
                ("Disney+ announces a new slate", True),
                ("Paramount+ pricing", True),
                ("disney+x launch", False),
            )
        ]
        + [
            {
                "case": "HTML 태그/속성/URL 안의 단어에도 반응",
                "title": "Apple event recap",
                "content": c,
                "legacy": gate("Apple event recap", c),
                "new_expected": False,
            }
            for c in (
                '<img src="https://x.com/movie.jpg"> text',
                '<a class="trailer-link">text</a>',
            )
        ],
    }

    # --- Discord 메시지 길이 초과 시 링크 유실 ------------------------
    captured = {}

    class _Resp:
        status_code = 204

    def _fake_post(url, json=None, timeout=None):
        captured["content"] = json["content"]
        return _Resp()

    reporter.requests.post = _fake_post
    item = {
        "site": "Blog",
        "link": "https://example.com/original-article",
        "translated_title": "제목",
        "published_dt": "2026-10-16T14:32:00+09:00",
    }
    message = reporter.format_discord_message(item, "가" * 2500)
    reporter.send_discord("http://example.invalid", message)
    golden["discord_message"] = {
        "known_defects": [
            {
                "case": "요약이 길면 끝부분(링크)이 잘려 나감",
                "legacy_input_length": len(message),
                "legacy_sent_length": len(captured["content"]),
                "legacy_link_preserved": item["link"] in captured["content"],
                "new_expected_link_preserved": True,
                "new_expected_max_length": 1900,
            }
        ]
    }
    return golden


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--legacy-dir", type=Path, default=Path("legacy"))
    parser.add_argument("--out", type=Path, default=Path("tests/golden/legacy_golden.json"))
    args = parser.parse_args()

    _pin_environment()
    golden = build_golden(args.legacy_dir.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(golden, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
