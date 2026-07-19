from typing import Any, Protocol

from app.schemas.natural_language import NaturalLanguageDiscoveryRequest


class NaturalLanguageDiscoveryInterpreter(Protocol):
    async def interpret(self, request: NaturalLanguageDiscoveryRequest) -> Any: ...
