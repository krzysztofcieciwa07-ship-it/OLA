from .contracts import ProviderError
from .gateway import ProviderGateway
from .ollama import OllamaAdapter
from .openai import OpenAIAdapter
from .lock import load_ollama_lock


def build_provider_gateway(provider: str) -> ProviderGateway:
    """Construct exactly one explicitly requested provider; never install a fallback."""
    if provider == "ollama":
        model, model_digest = load_ollama_lock()
        return ProviderGateway(ollama=OllamaAdapter(
            model=model,
            allowed_models=(model,),
            expected_model_digest=model_digest,
        ))
    if provider == "openai":
        return ProviderGateway(openai=OpenAIAdapter())
    raise ProviderError("unknown_provider", "provider must be explicitly set to ollama or openai")
