from .contracts import ProviderError
from .gateway import ProviderGateway
from .ollama import OllamaAdapter
from .openai import OpenAIAdapter


def build_provider_gateway(provider: str) -> ProviderGateway:
    """Construct exactly one explicitly requested provider; never install a fallback."""
    if provider == "ollama":
        return ProviderGateway(ollama=OllamaAdapter())
    if provider == "openai":
        return ProviderGateway(openai=OpenAIAdapter())
    raise ProviderError("unknown_provider", "provider must be explicitly set to ollama or openai")
