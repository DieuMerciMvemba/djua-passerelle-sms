from unittest.mock import MagicMock, patch
import unittest

from djua_sms_gateway.http.client import HttpResult, UrllibHttpClient


class UrllibHttpClientTests(unittest.TestCase):
    @patch("djua_sms_gateway.http.client.build_opener")
    def test_posts_exact_json_body_and_headers(self, build_opener):
        response = MagicMock()
        response.__enter__.return_value = response
        response.getcode.return_value = 201
        response.read.return_value = b'{"accepted":true}'
        opener = MagicMock()
        opener.open.return_value = response
        build_opener.return_value = opener
        body = '{"kit_id":"DJUA-1","value":0}'
        headers = {"Content-Type": "application/json", "X-DJUA-Topic": "a/b"}

        result = UrllibHttpClient(timeout_seconds=3).post_json(
            "https://backend.invalid/full/route", body, headers
        )

        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, body.encode("utf-8"))
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_header("X-djua-topic"), "a/b")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 3)
        self.assertEqual(result, HttpResult(201, '{"accepted":true}'))


if __name__ == "__main__":
    unittest.main()
