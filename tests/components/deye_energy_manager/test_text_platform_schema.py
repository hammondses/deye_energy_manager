"""Import the text platform against a small strict Home Assistant API stub."""

from dataclasses import dataclass
from enum import Enum
import importlib.util
from pathlib import Path
import sys
from types import ModuleType


def test_text_platform_imports_with_supported_text_schema(monkeypatch) -> None:
    class TextMode(str, Enum):
        TEXT = "text"
        PASSWORD = "password"

    @dataclass(frozen=True)
    class TextEntityDescription:
        key: str
        name: str | None = None
        icon: str | None = None
        mode: TextMode = TextMode.TEXT
        native_min: int = 0
        native_max: int = 255

        def __post_init__(self) -> None:
            if not isinstance(self.mode, TextMode):
                raise TypeError("mode must be TextMode.TEXT or TextMode.PASSWORD")
            if not 0 <= self.native_min <= self.native_max <= 255:
                raise ValueError("text length must be within 0..255")

    class TextEntity:
        pass

    module_types = {
        "homeassistant": ModuleType("homeassistant"),
        "homeassistant.components": ModuleType("homeassistant.components"),
        "homeassistant.components.text": ModuleType("homeassistant.components.text"),
        "homeassistant.config_entries": ModuleType("homeassistant.config_entries"),
        "homeassistant.core": ModuleType("homeassistant.core"),
        "homeassistant.helpers": ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.entity_platform": ModuleType("homeassistant.helpers.entity_platform"),
        "custom_components.deye_energy_manager.entity": ModuleType("custom_components.deye_energy_manager.entity"),
    }
    module_types["homeassistant.components.text"].TextEntity = TextEntity
    module_types["homeassistant.components.text"].TextEntityDescription = TextEntityDescription
    module_types["homeassistant.components.text"].TextMode = TextMode
    module_types["homeassistant.config_entries"].ConfigEntry = type("ConfigEntry", (), {})
    module_types["homeassistant.core"].HomeAssistant = type("HomeAssistant", (), {})
    module_types["homeassistant.helpers.entity_platform"].AddEntitiesCallback = type("AddEntitiesCallback", (), {})
    module_types["custom_components.deye_energy_manager.entity"].DeyeEnergyManagerEntity = type(
        "DeyeEnergyManagerEntity", (), {}
    )
    for name, module in module_types.items():
        monkeypatch.setitem(sys.modules, name, module)

    path = Path("custom_components/deye_energy_manager/text.py")
    spec = importlib.util.spec_from_file_location(
        "custom_components.deye_energy_manager.text_schema_test", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    description = module.TEXTS[0]
    assert description.mode is TextMode.TEXT
    assert description.native_min == 0
    assert description.native_max == 255
