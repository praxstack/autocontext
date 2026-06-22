from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from autocontext.harness.core.llm_client import LanguageModelClient
from autocontext.harness.core.types import ModelResponse

if TYPE_CHECKING:
    from autocontext.config.settings import AppSettings


@dataclass(frozen=True, slots=True)
class PanelParticipant:
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class PanelConfig:
    role: str
    participants: tuple[PanelParticipant, ...]
    synthesizer_provider: str = ""
    synthesizer_model: str = ""


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _parse_participant(value: str) -> PanelParticipant:
    if ":" not in value:
        return PanelParticipant(provider="", model=value.strip())
    provider, model = value.split(":", 1)
    return PanelParticipant(provider=provider.strip(), model=model.strip())


def _participants_for_role(spec: str, role: str) -> tuple[PanelParticipant, ...]:
    if not spec.strip():
        return ()
    selected = ""
    for chunk in [part.strip() for part in spec.split(";") if part.strip()]:
        if "=" not in chunk:
            selected = chunk
            continue
        key, value = chunk.split("=", 1)
        if key.strip() == role:
            selected = value
            break
    return tuple(_parse_participant(part) for part in _split_csv(selected))


def panel_config_for_role(settings: AppSettings, role: str) -> PanelConfig | None:
    roles = set(_split_csv(settings.panel_roles))
    if role not in roles:
        return None
    participants = _participants_for_role(settings.panel_participants, role)
    if not participants:
        return None
    return PanelConfig(
        role=role,
        participants=participants,
        synthesizer_provider=settings.panel_synthesizer_provider.strip(),
        synthesizer_model=settings.panel_synthesizer_model.strip(),
    )


ClientFactory = Callable[[str, str], LanguageModelClient]
WrapClient = Callable[[LanguageModelClient, str], LanguageModelClient]


def panel_client_for_role(
    settings: AppSettings,
    role: str,
    base_client: LanguageModelClient,
    *,
    scenario_name: str = "",
    generation_deadline: float | None = None,
    wrap_client: WrapClient | None = None,
) -> LanguageModelClient:
    from autocontext.agents.provider_bridge import create_role_client
    from autocontext.agents.role_runtime_overrides import settings_for_budgeted_role_call

    config = panel_config_for_role(settings, role)
    if config is None:
        return base_client

    def client_factory(provider_type: str, model: str) -> LanguageModelClient:
        call_settings, _is_budgeted = settings_for_budgeted_role_call(
            settings,
            provider_type,
            role,
            generation_deadline,
        )
        client = create_role_client(provider_type, call_settings, model_override=model, scenario_name=scenario_name, role=role)
        if client is None:
            return base_client
        return wrap_client(client, f"{provider_type}:{role}:panel") if wrap_client else client

    return PanelLanguageModelClient(role=role, base_client=base_client, config=config, client_factory=client_factory)


class PanelLanguageModelClient(LanguageModelClient):
    def __init__(
        self,
        *,
        role: str,
        base_client: LanguageModelClient,
        config: PanelConfig,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.role = role
        self.base_client = base_client
        self.config = config
        self.client_factory = client_factory

    def _client_for(self, provider: str, model: str) -> tuple[LanguageModelClient, bool]:
        if provider and self.client_factory is not None:
            return self.client_factory(provider, model), True
        return self.base_client, False

    def close(self) -> None:
        close = getattr(self.base_client, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _close_if_owned(client: LanguageModelClient, owned: bool) -> None:
        if not owned:
            return
        close = getattr(client, "close", None)
        if callable(close):
            close()

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        role: str = "",
    ) -> ModelResponse:
        started = time.monotonic()
        participant_records: list[dict[str, object]] = []
        total_cost = 0.0
        for participant in self.config.participants:
            participant_started = time.monotonic()
            participant_client, owned_client = self._client_for(participant.provider, participant.model)
            try:
                response = participant_client.generate(
                    model=participant.model,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    role=f"{self.role}:panel_participant",
                )
            finally:
                self._close_if_owned(participant_client, owned_client)
            latency_ms = int((time.monotonic() - participant_started) * 1000)
            cost = float(response.metadata.get("cost_usd", 0.0) or 0.0)
            total_cost += cost
            participant_records.append(
                {
                    "provider": participant.provider,
                    "model": participant.model,
                    "content": response.text.strip(),
                    "usage": asdict(response.usage),
                    "latency_ms": latency_ms,
                    "estimated_cost_usd": cost,
                }
            )

        synthesizer_model = self.config.synthesizer_model or model
        synth_prompt = _synthesis_prompt(self.role, prompt, participant_records)
        synth_started = time.monotonic()
        synth_client, owned_synth_client = self._client_for(self.config.synthesizer_provider, synthesizer_model)
        try:
            synth_response = synth_client.generate(
                model=synthesizer_model,
                prompt=synth_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                role=f"{self.role}:panel_synthesizer",
            )
        finally:
            self._close_if_owned(synth_client, owned_synth_client)
        synth_latency_ms = int((time.monotonic() - synth_started) * 1000)
        synth_cost = float(synth_response.metadata.get("cost_usd", 0.0) or 0.0)
        total_cost += synth_cost
        metadata = dict(synth_response.metadata)
        metadata.update(
            {
                "panel_runtime": True,
                "panel_role": self.role,
                "panel_participants": participant_records,
                "panel_synthesizer": {
                    "provider": self.config.synthesizer_provider,
                    "model": synthesizer_model,
                    "content": synth_response.text.strip(),
                    "usage": asdict(synth_response.usage),
                    "latency_ms": synth_latency_ms,
                    "estimated_cost_usd": synth_cost,
                },
                "panel_latency_ms": int((time.monotonic() - started) * 1000),
                "panel_estimated_cost_usd": round(total_cost, 6),
            }
        )
        return ModelResponse(text=synth_response.text, usage=synth_response.usage, metadata=metadata)


def _synthesis_prompt(role: str, original_prompt: str, participant_records: list[dict[str, object]]) -> str:
    outputs = "\n\n".join(
        f"[{index}] {item['provider']}:{item['model']}\n{item['content']}"
        for index, item in enumerate(participant_records, start=1)
    )
    return (
        f"You are synthesizing an experimental model panel for the {role} role.\n"
        "Return one final role response that preserves the expected contract.\n\n"
        f"Original prompt:\n{original_prompt}\n\n"
        f"Participant outputs:\n{outputs}"
    )


def compare_panel_benchmark(
    *,
    single_score: float,
    panel_score: float,
    single_latency_ms: float,
    panel_latency_ms: float,
    single_cost_usd: float,
    panel_cost_usd: float,
) -> dict[str, float]:
    single_score_per_cost = single_score / single_cost_usd if single_cost_usd > 0 else 0.0
    panel_score_per_cost = panel_score / panel_cost_usd if panel_cost_usd > 0 else 0.0
    return {
        "score_delta": round(panel_score - single_score, 6),
        "latency_ms_delta": round(panel_latency_ms - single_latency_ms, 6),
        "cost_usd_delta": round(panel_cost_usd - single_cost_usd, 6),
        "score_per_cost_delta": round(panel_score_per_cost - single_score_per_cost, 6),
    }
