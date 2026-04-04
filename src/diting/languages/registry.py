"""语言插件注册表"""
import logging
from typing import Optional

from diting.graph.client import GraphClient
from diting.languages.base import LanguagePlugin

logger = logging.getLogger(__name__)

_registry: dict[str, type[LanguagePlugin]] = {}


def register(name: str):
    """装饰器：注册语言插件

    用法::

        @register("java")
        class JavaPlugin(LanguagePlugin):
            ...
    """
    def wrapper(cls: type[LanguagePlugin]) -> type[LanguagePlugin]:
        _registry[name] = cls
        logger.debug("Registered language plugin: %s -> %s", name, cls.__name__)
        return cls
    return wrapper


def get_plugin(name: str, graph_client: GraphClient) -> LanguagePlugin:
    """获取指定语言的插件实例"""
    if name not in _registry:
        available = list(_registry.keys())
        raise ValueError(f"Unknown language '{name}'. Available: {available}")
    return _registry[name](graph_client)


def list_plugins() -> list[str]:
    """列出所有已注册的语言"""
    return list(_registry.keys())


def ensure_plugins_loaded():
    """确保所有内置插件已加载（触发模块导入）"""
    import importlib
    for lang in ("java", "python"):
        try:
            importlib.import_module(f"diting.languages.{lang}")
        except ImportError as e:
            logger.warning("Failed to load language plugin '%s': %s", lang, e)


def get_plugin_optional(name: Optional[str], graph_client: GraphClient) -> Optional[LanguagePlugin]:
    """可选版本：name 为 None 时返回 None"""
    if not name:
        return None
    return get_plugin(name, graph_client)
