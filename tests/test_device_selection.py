import asyncio
from types import SimpleNamespace

import pytest
from adam.compute.catalog import Catalog, ModelProfile, publish, read_catalog
from adam.compute.contracts import ComputeError
from adam.compute.migration import ModelController
from adam.compute.owned import OwnedLlamaProvider
from adam.compute.resources import ManagedProvider
from adam.core.config import Settings
from adam.models.base import ModelHealth


@pytest.mark.parametrize(
    "failure", [None, "MODEL.GPU_UNAVAILABLE", "RESOURCE.VRAM_BUDGET", "cancel"]
)
def test_device_change_persists_success_and_restores_cpu_on_failure(tmp_path, failure):
    async def scenario():
        settings = Settings(data_dir=tmp_path)
        profile = ModelProfile(
            profile_id="current", model=settings.model, managed=True, model_file="fixture.gguf"
        )
        publish(tmp_path, "config/model-catalog.json", Catalog(profiles={"current": profile}))
        steps = []

        class FakeOwned(OwnedLlamaProvider):
            async def load(self):
                steps.append("load-" + self.profile.device)
                if self.profile.device == "vulkan" and failure:
                    if failure == "cancel":
                        raise asyncio.CancelledError
                    raise ComputeError(failure)
                self.process = SimpleNamespace(poll=lambda: None)
                return ModelHealth(status="HEALTHY", model_id=self.config.model_id)

            async def unload(self):
                steps.append("unload-" + self.profile.device)
                self.process = None

        manager = ManagedProvider(FakeOwned(profile), settings)
        manager.sampler = lambda: {
            "ram_available_bytes": 8 * 1024**3,
            "ram_used_percent": 40,
            "disk_free_bytes": 8 * 1024**3,
        }
        manager.gpu_probe = lambda: [{"vram_total_bytes": 8 * 1024**3, "vram_used_bytes": 0}]
        controller = ModelController(manager)
        controller.factory = FakeOwned
        manager.delegate = FakeOwned(profile)
        await manager.load()
        if failure:
            with pytest.raises(asyncio.CancelledError if failure == "cancel" else ComputeError):
                await controller.set_device("vulkan")
            assert manager.delegate.profile.device == "cpu"
            assert (
                read_catalog(tmp_path / "config/model-catalog.json").profiles["current"].device
                == "cpu"
            )
            if failure != "cancel":
                assert manager.error is None and manager.delegate.process is not None
            else:
                assert manager.error == "MODEL.LOAD_CANCELLED" and manager.detached
        else:
            assert (await controller.set_device("vulkan"))["status"] == "HEALTHY"
            assert manager.delegate.profile.device == "vulkan"
            assert (
                read_catalog(tmp_path / "config/model-catalog.json").profiles["current"].device
                == "vulkan"
            )
            before = list(steps)
            assert not (await controller.set_device("vulkan"))["changed"]
            assert steps == before
        assert not manager.operation_active and manager.operation_idle.is_set()
        assert steps.index("unload-cpu") < steps.index("load-vulkan")

    asyncio.run(scenario())


def test_device_endpoint_is_owner_only_and_rejects_unknown_devices(tmp_path):
    from adam.api.app import create_app
    from adam.evals.suite import ProbeProvider
    from fastapi.testclient import TestClient

    app = create_app(Settings(data_dir=tmp_path), ProbeProvider())
    password = "synthetic-device-owner-passphrase"
    app.state.auth.initialize(password)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.post("/model/device", json={"device": "vulkan"}).status_code == 401
        client.post("/auth/login", json={"password": password})
        assert client.post("/model/device", json={"device": "cuda"}).status_code == 422
        assert (
            client.post("/model/device", json={"device": "vulkan"}).json()["error"]
            == "MODEL.DEVICE_EXTERNAL"
        )
        client.post("/auth/switch", json={"mode": "guest"})
        assert client.post("/model/device", json={"device": "cpu"}).status_code == 403
