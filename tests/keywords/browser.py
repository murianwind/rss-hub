"""브라우저 요청 키워드."""

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
CROSS_SITE = {"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"}
FRAGMENT = {"x-panel": "1"}


def post(world, path, **data):
    """같은 출처의 브라우저가 양식을 보낸다."""
    return world.client.post(path, data=data, headers=BROWSER)
