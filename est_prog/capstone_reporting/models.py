"""Resolve configured models through PydanticAI; preserve the Responses default."""
from pydantic_ai.models import Model, infer_model


def resolve_model(model: str | Model) -> Model:
    if isinstance(model, Model):
        return model
    if ":" not in model or model.startswith("openai:"):
        model = "openai-responses:" + model.removeprefix("openai:")
    return infer_model(model)
