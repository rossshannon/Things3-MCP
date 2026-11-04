"""Fixed Things action schemas, excluding caller-selected databases or scripts."""

from clawbridge.actions import Action

TEXT = (str, type(None))
FILTER = (str, bool, type(None))
BOOL = (bool, type(None))
STRINGS = (list, type(None))
TASK_FILTERS = {
    **dict.fromkeys(("uuid", "type", "status", "start", "index", "search_query", "last"), TEXT),
    **dict.fromkeys(("area", "project", "heading", "tag", "start_date", "stop_date", "deadline"), FILTER),
    **dict.fromkeys(("deadline_suppressed", "trashed", "context_trashed", "include_items", "count_only"), BOOL),
}
COMMON_WRITE = dict.fromkeys(("title", "notes", "when", "deadline"), TEXT)
ACTIONS = {name: Action(name, fields={"include_items": bool}) for name in ("inbox", "today", "upcoming", "anytime", "someday", "trash")}
ACTIONS.update(
    {
        "get": Action("get", fields={"uuid": str}, required=frozenset({"uuid"}), nonempty=frozenset({"uuid"})),
        "last": Action("last", fields={"period": str, "include_items": bool}, required=frozenset({"period"}), nonempty=frozenset({"period"})),
        "search": Action("search", fields={"query": str, "include_items": bool}, required=frozenset({"query"})),
        "tasks": Action("tasks", fields=TASK_FILTERS),
        "todos": Action("todos", fields={key: value for key, value in TASK_FILTERS.items() if key != "type"}),
        "projects": Action("projects", fields={key: value for key, value in TASK_FILTERS.items() if key != "type"}),
        "areas": Action("areas", fields={"uuid": TEXT, "tag": FILTER, "include_items": bool, "count_only": bool}),
        "tags": Action("tags", fields={"title": TEXT, "area": TEXT, "task": TEXT, "include_items": bool, "titles_only": bool}),
        "snapshot": Action("snapshot"),
        "diagnose": Action("diagnose"),
        "add_task": Action("add_task", True, {**COMMON_WRITE, "tags": STRINGS, "list_id": TEXT, "list_title": TEXT}, frozenset({"title"}), nonempty=frozenset({"title"})),
        "update_task": Action(
            "update_task",
            True,
            {**COMMON_WRITE, "uuid": str, "tags": (list, str, type(None)), "add_tags": (list, str, type(None)), "completed": BOOL, "canceled": BOOL, "list_id": TEXT, "list_name": TEXT},
            frozenset({"uuid"}),
            nonempty=frozenset({"uuid"}),
        ),
        "add_project": Action("add_project", True, {**COMMON_WRITE, "tags": STRINGS, "todos": STRINGS, "area_id": TEXT, "area_title": TEXT}, frozenset({"title"}), nonempty=frozenset({"title"})),
        "update_project": Action(
            "update_project",
            True,
            {**COMMON_WRITE, "uuid": str, "tags": STRINGS, "completed": BOOL, "canceled": BOOL, "list_name": TEXT, "area_id": TEXT, "area_title": TEXT},
            frozenset({"uuid"}),
            nonempty=frozenset({"uuid"}),
        ),
    }
)
