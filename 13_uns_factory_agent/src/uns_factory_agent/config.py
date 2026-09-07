from uns_config import get_settings

_settings = get_settings("factory_agent")


class FactoryAgentConfig:
    model: str = str(_settings.get("factory_agent.model", "gpt-4o"))
    graphql_url: str = str(_settings.get("factory_agent.graphql_url", "http://localhost:8000/graphql"))
    openai_api_key: str = str(_settings.get("factory_agent.openai_api_key", ""))
