from pathlib import Path

import pytest

from hexworld.agents.fake import FakeClient
from hexworld.agents.kit import fake_model_factory
from hexworld.art.backend import ProceduralStubBackend
from hexworld.config import Settings
from hexworld.orchestrator.runtime import Runtime
from hexworld.store import Store


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None, data_dir=tmp_path / "data", llm="fake", image="stub", image_fallback="none"
    )


@pytest.fixture
def make_runtime(settings):
    created: list[Runtime] = []

    def _make(llm=None, image=None, store=None, **overrides) -> Runtime:
        s = settings.model_copy(update=overrides)
        brain = llm or FakeClient(latency_s=0, reject_rate=s.fake_reject_rate)  # scripted agent brain
        rt = Runtime(
            s,
            store=store or Store(s.data_dir),
            model_factory=fake_model_factory(brain, latency_s=brain.latency_s),
            image=image or ProceduralStubBackend(latency_s=0),
        )
        created.append(rt)
        return rt

    yield _make
    for rt in created:
        rt.store.close()
