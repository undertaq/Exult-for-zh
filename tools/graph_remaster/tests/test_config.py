from pathlib import Path

import pytest

from graph_remaster.config import PipelineConfig, load_config
from graph_remaster.errors import ConfigError


def test_load_config_resolves_relative_paths(tmp_path: Path) -> None:
    config = tmp_path / "pipeline.toml"
    config.write_text(
        """[project]\nname = 'black-gate'\n[paths]\ndata = 'game-data'\nwork = 'remaster-data'\n[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n""",
        encoding="utf-8",
    )

    loaded = load_config(config)

    assert loaded.render.scale == 6
    assert loaded.paths.data == tmp_path / "game-data"
    assert loaded.render.logical_size == (320, 200)


@pytest.mark.parametrize(
    ("section", "values"),
    [
        ("render", {"scale": 5}),
        ("render", {"logical_width": 640}),
        ("render", {"logical_height": 240}),
    ],
)
def test_from_mapping_rejects_noncanonical_render_settings(
    section: str, values: dict[str, int]
) -> None:
    mapping = {
        "project": {"name": "black-gate"},
        "paths": {"data": "game-data", "work": "remaster-data"},
        "render": {"scale": 6, "logical_width": 320, "logical_height": 200},
    }
    mapping[section].update(values)

    with pytest.raises(ConfigError, match="render"):
        PipelineConfig.from_mapping(mapping)


def test_from_mapping_rejects_missing_required_paths() -> None:
    with pytest.raises(ConfigError, match="paths.data"):
        PipelineConfig.from_mapping(
            {
                "project": {"name": "black-gate"},
                "paths": {"work": "remaster-data"},
                "render": {"scale": 6, "logical_width": 320, "logical_height": 200},
            }
        )


def test_from_mapping_rejects_non_black_gate_projects() -> None:
    with pytest.raises(ConfigError, match="black-gate"):
        PipelineConfig.from_mapping(
            {
                "project": {"name": "serpent-isle"},
                "paths": {"data": "game-data", "work": "remaster-data"},
                "render": {"scale": 6, "logical_width": 320, "logical_height": 200},
            }
        )


def test_gpu_defaults_provide_one_worker_per_default_gpu() -> None:
    loaded = PipelineConfig.from_mapping(
        {
            "project": {"name": "black-gate"},
            "paths": {"data": "game-data", "work": "remaster-data"},
            "render": {"scale": 6, "logical_width": 320, "logical_height": 200},
        }
    )

    assert loaded.gpu.devices == ("cuda:0", "cuda:1")
    assert loaded.gpu.workers == 2


def test_gpu_workers_cannot_exceed_devices() -> None:
    with pytest.raises(ConfigError, match="workers.*devices"):
        PipelineConfig.from_mapping(
            {
                "project": {"name": "black-gate"},
                "paths": {"data": "game-data", "work": "remaster-data"},
                "render": {"scale": 6, "logical_width": 320, "logical_height": 200},
                "gpu": {"devices": ["cuda:0"], "workers": 2},
            }
        )


def test_gpu_devices_must_be_a_sequence() -> None:
    with pytest.raises(ConfigError, match="gpu.devices"):
        PipelineConfig.from_mapping(
            {
                "project": {"name": "black-gate"},
                "paths": {"data": "game-data", "work": "remaster-data"},
                "render": {"scale": 6, "logical_width": 320, "logical_height": 200},
                "gpu": {"devices": "cuda:0"},
            }
        )
