"""Portable AX graph tests; no desktop content or input is accessed."""

import sys
from types import SimpleNamespace

import pytest
from agentbot_macos import accessibility as ax
from agentbot_macos.results import NotDispatched


class Element:
    def __init__(self, role="AXGroup", children=(), **attributes):
        self.values = {"AXRole": role, "AXChildren": list(children), **attributes}
        self.errors = {}


@pytest.fixture
def tree(monkeypatch):
    root = Element("AXWindow")
    reads = []

    def attribute(element, name, unused):
        reads.append((element, name))
        error = element.errors.get(name, 0 if name in element.values else -25205)
        return error, element.values.get(name)

    monkeypatch.setitem(
        sys.modules,
        "ApplicationServices",
        SimpleNamespace(
            AXUIElementCopyAttributeValue=attribute,
            AXUIElementIsAttributeSettable=lambda *a: (0, True),
        ),
    )
    monkeypatch.setattr(ax, "window_element", lambda window: root)
    monkeypatch.setattr(ax, "bounds", lambda element: [0.0, 0.0, 100.0, 100.0])
    monkeypatch.setattr(ax.time, "monotonic", lambda: 0.0)
    return root, reads


def test_large_window_scanned_completely_with_bounded_controls(tree):
    root, reads = tree
    editor = Element("AXTextField", AXValue="owned text", AXFocused=True)
    root.values["AXChildren"] = [Element() for _ in range(815)] + [editor]
    controls, handles = ax.inspect({})
    assert len(controls) == len(handles) == 300
    assert sum(name == "AXRole" for _, name in reads) == 817
    assert controls[0]["editable"] and controls[0]["focused"] and controls[0]["writable"]
    assert controls[0]["value"] == "owned text"
    assert handles[controls[0]["id"]] is editor


@pytest.mark.parametrize("role", ["AXTextField", "AXSecureTextField"])
def test_secure_field_beyond_old_control_limit_rejects_before_values(tree, role):
    root, reads = tree
    secure = Element(role, AXSubrole="AXSecureTextField", AXValue="never read")
    root.values["AXChildren"] = [Element() for _ in range(400)] + [Element(children=[secure])]
    with pytest.raises(NotDispatched, match="Secure input") as error:
        ax.inspect({})
    assert error.value.result()["code"] == "secure_surface"
    assert not any(name == "AXValue" for _, name in reads)


def test_shared_descendants_and_cycles_do_not_consume_budget_twice(tree):
    root, reads = tree
    child = Element(children=[root])
    root.values["AXChildren"] = [child] * 400
    controls, _ = ax.inspect({})
    assert len(controls) == 2
    assert sum(name == "AXRole" for _, name in reads) == 2


def test_node_limit_counts_elements_without_geometry(tree, monkeypatch):
    root, _ = tree
    monkeypatch.setattr(ax, "MAX_ELEMENTS", 8)
    monkeypatch.setattr(ax, "bounds", lambda element: None)
    root.values["AXChildren"] = [Element() for _ in range(8)]
    with pytest.raises(NotDispatched, match="exceeded 8 elements"):
        ax.inspect({})


@pytest.mark.parametrize("attribute", ["AXRole", "AXSubrole", "AXChildren"])
def test_failed_security_reads_cannot_be_treated_as_empty_tree(tree, attribute):
    root, _ = tree
    child = Element("AXTextField")
    child.errors[attribute] = -25204  # Cannot complete (for example, application hung).
    root.values["AXChildren"] = [child]
    with pytest.raises(NotDispatched, match="could not be read completely"):
        ax.inspect({})


@pytest.mark.parametrize("error", [-25205, -25212])
def test_optional_attributes_can_be_absent_on_leaves(tree, error):
    root, _ = tree
    root.errors.update(AXSubrole=error, AXChildren=error)
    controls, _ = ax.inspect({})
    assert len(controls) == 1


def test_display_security_scan_does_not_collect_values_or_geometry(tree, monkeypatch):
    root, reads = tree
    root.values["AXChildren"] = [Element("AXTextField", AXValue="not needed")]

    def unexpected(element):
        pytest.fail("Security-only scan must not fetch control geometry")

    monkeypatch.setattr(ax, "bounds", unexpected)
    assert ax.inspect({}, include_controls=False) == ([], {})
    assert {name for _, name in reads} == {"AXRole", "AXSubrole", "AXChildren"}


@pytest.mark.parametrize("phase", ["tree", "metadata"])
def test_deadline_expiring_during_last_element_still_rejects(tree, monkeypatch, phase):
    now = [0.0]
    monkeypatch.setattr(ax.time, "monotonic", lambda: now[0])
    if phase == "tree":
        original = ax._checked_attribute

        def delayed(element, name, default=None):
            value = original(element, name, default)
            if name == "AXChildren":
                now[0] = 4.0
            return value

        monkeypatch.setattr(ax, "_checked_attribute", delayed)
    else:

        def delayed_bounds(element):
            now[0] = 4.0
            return [0, 0, 100, 100]

        monkeypatch.setattr(ax, "bounds", delayed_bounds)
    with pytest.raises(NotDispatched, match="timed out"):
        ax.inspect({}, deadline=3.0)
