import unittest
from backend.provider import Provider

class OutputTests(unittest.TestCase):
    def provider(self,content,finish="stop",base="https://tokenhub.tencentmaas.com/v1"):
        class Capture(Provider):
            def request(self,endpoint,payload):
                self.payload=payload
                return {"choices":[{"message":{"content":content},"finish_reason":finish}]}
        return Capture({"base_url":base,"model":"deepseek-v4.1-flash"},"fixture")
    def test_documented_tokenhub_json_mode_and_explicit_budget(self):
        p=self.provider('{"title":"ok"}');p.json("Return JSON",{})
        self.assertEqual(p.payload.get("response_format"),{"type":"json_object"})
        self.assertGreaterEqual(p.payload.get("max_tokens",0),16000)
    def test_malformed_json_retains_raw_text_and_exact_parse_location(self):
        p=self.provider('{"title":"unterminated')
        with self.assertRaises(ValueError) as caught:p.json("Return JSON",{})
        err=caught.exception
        self.assertEqual(getattr(err,"raw_result",{}).get("response_text"),'{"title":"unterminated')
        self.assertEqual(err.errors[0]["code"],"malformed_json")
        self.assertGreater(err.errors[0]["column"],0)
    def test_length_finish_never_accepts_a_valid_but_incomplete_object(self):
        p=self.provider('{"title":"ok"}',"length")
        with self.assertRaises(ValueError) as caught:p.json("Return JSON",{})
        self.assertEqual(caught.exception.errors[0]["code"],"output_truncated")
        self.assertEqual(caught.exception.raw_result["finish_reason"],"length")
    def test_other_providers_keep_compatible_request_fields(self):
        p=self.provider('{"title":"ok"}',base="https://example.com/v1");p.json("Return JSON",{})
        self.assertNotIn("response_format",p.payload)
        self.assertNotIn("max_tokens",p.payload)

if __name__=="__main__":unittest.main()
