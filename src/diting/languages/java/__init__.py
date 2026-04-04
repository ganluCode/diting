from diting.languages.registry import register
from .plugin import JavaPlugin

register("java")(JavaPlugin)

__all__ = ["JavaPlugin"]
