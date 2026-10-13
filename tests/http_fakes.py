"""Small HTTP doubles: preserve real request boundaries without network access."""

from dataclasses import dataclass, field


@dataclass
class Response:
    payload: object = None
    status_code: int = 200
    headers: dict = field(default_factory=dict)

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def _request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected {method}: {url}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._request("POST", url, **kwargs)
