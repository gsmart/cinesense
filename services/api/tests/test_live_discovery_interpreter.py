import httpx
import pytest

from app.interpreters import (
    InterpreterFailureError,
    OpenAICompatibleNaturalLanguageDiscoveryInterpreter,
)
from app.schemas.natural_language import NaturalLanguageDiscoveryRequest


def make_request() -> NaturalLanguageDiscoveryRequest:
    return NaturalLanguageDiscoveryRequest(query="Marathi thrillers released between 2016 and 2018")


def make_client_factory(handler):
    return lambda: httpx.AsyncClient(
        base_url="https://example.test/openai/v1",
        timeout=5.0,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.anyio
async def test_live_interpreter_returns_valid_strict_json_object():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/openai/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer secret-key"
        payload = request.read().decode()
        assert '"model":"llama-test"' in payload
        assert '"response_format":{"type":"json_object"}' in payload
        assert 'Allowed keys: genres, original_language, region, release_year_min, release_year_max, runtime_minutes_min, runtime_minutes_max, minimum_evidence_count, availability_required, media_type.' in payload
        assert 'Example output: {\\"genres\\":[\\"thriller\\"],\\"original_language\\":\\"mr\\",\\"release_year_min\\":2016,\\"release_year_max\\":2018}' in payload
        assert 'Interpret this movie discovery query into one JSON object only: Marathi thrillers released between 2016 and 2018' in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"genres":["thriller"],"original_language":"mr","release_year_min":2016,"release_year_max":2018}'
                        }
                    }
                ]
            },
        )

    interpreter = OpenAICompatibleNaturalLanguageDiscoveryInterpreter(
        base_url="https://example.test/openai/v1",
        api_key="secret-key",
        model="llama-test",
        timeout_seconds=5.0,
        client_factory=make_client_factory(handler),
    )

    result = await interpreter.interpret(make_request())

    assert result == {
        "genres": ["thriller"],
        "original_language": "mr",
        "release_year_min": 2016,
        "release_year_max": 2018,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"error": "bad"}),
        httpx.Response(200, json={"choices": [{"message": {"content": "```json\n{}\n```"}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "[1,2,3]"}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "{"}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}),
        httpx.Response(200, json={"choices": [{}]}),
    ],
)
async def test_live_interpreter_rejects_unsafe_or_invalid_provider_responses(response: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    interpreter = OpenAICompatibleNaturalLanguageDiscoveryInterpreter(
        base_url="https://example.test/openai/v1",
        api_key="secret-key",
        model="llama-test",
        timeout_seconds=5.0,
        client_factory=make_client_factory(handler),
    )

    with pytest.raises(InterpreterFailureError) as exc_info:
        await interpreter.interpret(make_request())

    assert "secret-key" not in str(exc_info.value)
    assert "example.test" not in str(exc_info.value)


@pytest.mark.anyio
async def test_live_interpreter_timeout_returns_controlled_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    interpreter = OpenAICompatibleNaturalLanguageDiscoveryInterpreter(
        base_url="https://example.test/openai/v1",
        api_key="secret-key",
        model="llama-test",
        timeout_seconds=5.0,
        client_factory=make_client_factory(handler),
    )

    with pytest.raises(InterpreterFailureError) as exc_info:
        await interpreter.interpret(make_request())

    assert "secret-key" not in str(exc_info.value)
