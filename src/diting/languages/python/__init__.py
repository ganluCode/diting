from diting.languages.registry import register
from .plugin import PythonPlugin

register("python")(PythonPlugin)

__all__ = ["PythonPlugin"]
