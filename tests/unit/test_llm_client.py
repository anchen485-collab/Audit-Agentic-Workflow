import httpx

from app.infrastructure.llm_client import MockLLMClient, OpenAICompatibleLLMClient


def test_mock_llm_client_returns_configured_json():
    client = MockLLMClient(response={"action": "approved"})

    assert client.complete_json("prompt") == {"action": "approved"}


def test_openai_compatible_llm_client_parses_json_content():
    def fake_post(url: str, **kwargs):
        return httpx.Response(
            status_code=200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"action": "approved", "confidence": 90}',
                        }
                    }
                ]
            },
            request=httpx.Request("POST", url),
        )

    client = OpenAICompatibleLLMClient(
        api_key="test",
        base_url="https://example.com/v1",
        model="test-model",
        http_post=fake_post,
    )

    assert client.complete_json("prompt") == {"action": "approved", "confidence": 90}
