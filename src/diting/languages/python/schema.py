"""Python 图谱 Schema 声明（独立于 Java，标签前缀 Python:）"""
from diting.languages.base import LanguageSchema, RelationshipDef

PYTHON_SCHEMA = LanguageSchema(
    labels={
        "Python:Package": {"fqn": str, "name": str, "project": str},
        "Python:Module":  {
            "fqn": str, "name": str, "project": str,
            "file_path": str, "line_count": int, "docstring": str,
        },
        "Python:Class": {
            "fqn": str, "name": str, "project": str,
            "module_fqn": str, "line_number": int,
            "docstring": str, "is_dataclass": bool,
        },
        "Python:Function": {
            "fqn": str, "name": str, "project": str,
            "module_fqn": str, "class_fqn": str,
            "line_number": int, "docstring": str,
            "is_method": bool, "is_static": bool,
            "is_classmethod": bool, "is_property": bool, "is_async": bool,
            "parameter_count": int,
        },
    },
    relationships={
        "CONTAINS":     RelationshipDef("Python:Package", "Python:Module"),
        "DECLARES":     RelationshipDef("Python:Class",   "Python:Function"),
        "EXTENDS":      RelationshipDef("Python:Class",   "Python:Class"),
        "INVOKES":      RelationshipDef("Python:Function","Python:Function"),
        "IMPORTS":      RelationshipDef("Python:Module",  "Python:Module"),
        "OVERRIDES":    RelationshipDef("Python:Function","Python:Function"),
        "DECORATED_BY": RelationshipDef("Python:Function","Python:Function"),
    },
    indexes=[
        ("Python:Module",   ["fqn"]),
        ("Python:Class",    ["fqn"]),
        ("Python:Function", ["fqn"]),
        ("Python:Package",  ["fqn"]),
        ("Python:Module",   ["project"]),
        ("Python:Class",    ["project"]),
        ("Python:Function", ["project"]),
    ],
    enhanced_relationships=["OVERRIDES"],
)
