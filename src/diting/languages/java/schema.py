"""Java 图谱 Schema 声明"""
from diting.languages.base import LanguageSchema, RelationshipDef

JAVA_SCHEMA = LanguageSchema(
    labels={
        "Java:Type:Class": {
            "fqn": str, "name": str, "project": str,
            "abstract": bool,
        },
        "Java:Type:Interface": {
            "fqn": str, "name": str, "project": str,
        },
        "Java:Type:Enum": {
            "fqn": str, "name": str, "project": str,
        },
        "Java:Method": {
            "name": str, "signature": str, "visibility": str,
            "summary": str, "lineNumber": int,
            "effectiveLineCount": int, "cyclomaticComplexity": int,
        },
        "Java:Field": {
            "name": str, "signature": str,
        },
        "Spring:Injectable": {
            "fqn": str, "name": str, "project": str,
        },
    },
    relationships={
        # 原生关系（jQAssistant 生成）
        "DECLARES":      RelationshipDef("Java:Type", "Java:Method"),
        "INVOKES":       RelationshipDef("Java:Method", "Java:Method"),
        "IMPLEMENTS":    RelationshipDef("Java:Type", "Java:Type"),
        "EXTENDS":       RelationshipDef("Java:Type", "Java:Type"),
        "ANNOTATED_BY":  RelationshipDef("Java:Type", "Java:Type"),
        "OF_TYPE":       RelationshipDef("Java:Type", "Java:Type"),
        "DEPENDS_ON":    RelationshipDef("Java:Type", "Java:Type"),
        # 增强关系
        "ASSIGNABLE_FROM":   RelationshipDef("Java:Type", "Java:Type"),
        "INHERITED_FROM":    RelationshipDef("Java:Method", "Java:Method"),
        "OVERRIDES":         RelationshipDef("Java:Method", "Java:Method"),
        "VIRTUAL_INVOKES":   RelationshipDef("Java:Method", "Java:Method"),
        "VIRTUAL_DEPENDS_ON":RelationshipDef("Java:Type", "Java:Type"),
        "RESOLVED_INVOKES":  RelationshipDef(
            "Java:Method", "Java:Method", {"dispatch_type": str}
        ),
        "INJECTS":       RelationshipDef("Java:Type", "Java:Type", {"field": str}),
        "PRODUCES_BEAN": RelationshipDef("Java:Method", "Java:Type"),
        "PUBLISHES_EVENT":   RelationshipDef("Java:Method", "Java:Type"),
        "HANDLES_EVENT":     RelationshipDef("Java:Method", "Java:Type"),
        "EVENT_ROUTES_TO":   RelationshipDef("Java:Method", "Java:Method"),
        "ADVISES":       RelationshipDef("Java:Method", "Java:Method"),
    },
    indexes=[
        ("Java:Type", ["fqn"]),
        ("Java:Type", ["project"]),
        ("Java:Type", ["name"]),
        ("Java:Method", ["signature"]),
        ("Java:Method", ["name"]),
    ],
    enhanced_relationships=[
        "ASSIGNABLE_FROM", "INHERITED_FROM", "OVERRIDES",
        "VIRTUAL_INVOKES", "VIRTUAL_DEPENDS_ON", "INJECTS",
        "PRODUCES_BEAN", "RESOLVED_INVOKES",
        "PUBLISHES_EVENT", "HANDLES_EVENT", "EVENT_ROUTES_TO",
        "ADVISES",
    ],
)
