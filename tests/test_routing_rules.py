"""TG.2 — routing-rule storage + evaluator.

Each rule is a *conditional*: "when a device matches `device_match`, the
worker that builds for it must also match `worker_match`." A rule passes
(does not disqualify) for a (device, worker) pair when either:
  - the device does NOT match the rule's ``device_match`` (rule doesn't
    apply), OR
  - the device DOES match AND the worker also matches ``worker_match``.

The fleet-wide ``is_eligible(device, worker, rules)`` ANDs every rule —
any single failing rule blocks the worker from claiming a job for that
device.

Severity is reserved for future expansion (`preferred` with weights);
the only accepted value in 1.7.0 is ``"required"`` — anything else is
rejected at load time with a clear error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from routing import (
    Clause,
    Rule,
    RoutingRuleError,
    RoutingRuleStore,
    evaluate_clause,
    evaluate_rule,
    is_eligible,
)


# ---------------------------------------------------------------------------
# evaluate_clause — single-side clause evaluation
# ---------------------------------------------------------------------------


def test_clause_all_of_pass() -> None:
    c = Clause(op="all_of", tags=["kitchen", "production"])
    assert evaluate_clause(c, {"kitchen", "production", "linux"}) is True


def test_clause_all_of_fail_on_missing() -> None:
    c = Clause(op="all_of", tags=["kitchen", "production"])
    assert evaluate_clause(c, {"kitchen"}) is False


def test_clause_any_of_pass_on_one_match() -> None:
    c = Clause(op="any_of", tags=["kitchen", "garage"])
    assert evaluate_clause(c, {"garage"}) is True


def test_clause_any_of_fail_on_no_match() -> None:
    c = Clause(op="any_of", tags=["kitchen", "garage"])
    assert evaluate_clause(c, {"office"}) is False


def test_clause_none_of_pass_when_absent() -> None:
    c = Clause(op="none_of", tags=["staging"])
    assert evaluate_clause(c, {"production"}) is True


def test_clause_none_of_fail_when_present() -> None:
    c = Clause(op="none_of", tags=["staging"])
    assert evaluate_clause(c, {"staging", "linux"}) is False


def test_clause_unknown_op_raises() -> None:
    c = Clause(op="includes", tags=["x"])  # type: ignore[arg-type]
    with pytest.raises(RoutingRuleError):
        evaluate_clause(c, {"x"})


# ---------------------------------------------------------------------------
# evaluate_rule — conditional: when device matches, worker must match
# ---------------------------------------------------------------------------


def _rule(*, device_tags=("kitchen",), worker_tags=("kitchen",), op="all_of") -> Rule:
    return Rule(
        id="r1",
        name="r1",
        severity="required",
        device_match=[Clause(op=op, tags=list(device_tags))],
        worker_match=[Clause(op=op, tags=list(worker_tags))],
    )


def test_rule_passes_when_device_does_not_match() -> None:
    """Rule doesn't apply to this device → automatic pass (worker irrelevant)."""
    r = _rule(device_tags=("kitchen",), worker_tags=("kitchen",))
    assert evaluate_rule(r, ["office"], []) is True


def test_rule_passes_when_device_matches_and_worker_matches() -> None:
    r = _rule(device_tags=("kitchen",), worker_tags=("kitchen",))
    assert evaluate_rule(r, ["kitchen"], ["kitchen"]) is True


def test_rule_fails_when_device_matches_and_worker_does_not() -> None:
    r = _rule(device_tags=("kitchen",), worker_tags=("kitchen",))
    assert evaluate_rule(r, ["kitchen"], ["other"]) is False


def test_rule_clauses_anded_within_each_side() -> None:
    """Compound clauses on the same side AND together."""
    r = Rule(
        id="r1",
        name="r1",
        severity="required",
        device_match=[
            Clause(op="all_of", tags=["kitchen"]),
            Clause(op="none_of", tags=["staging"]),
        ],
        worker_match=[Clause(op="all_of", tags=["fast"])],
    )
    # Device kitchen+production passes both device clauses; needs worker fast.
    assert evaluate_rule(r, ["kitchen", "production"], ["fast"]) is True
    # Device kitchen+staging fails the second device clause → rule doesn't apply.
    assert evaluate_rule(r, ["kitchen", "staging"], []) is True
    # Device matches but worker isn't fast → rule fires, fail.
    assert evaluate_rule(r, ["kitchen"], ["slow"]) is False


# ---------------------------------------------------------------------------
# is_eligible — every rule ANDed; one failing rule blocks the worker
# ---------------------------------------------------------------------------


def test_is_eligible_empty_rules_always_true() -> None:
    assert is_eligible([], [], []) is True
    assert is_eligible(["any"], ["thing"], []) is True


def test_is_eligible_single_rule_passes() -> None:
    r = _rule(device_tags=("prod",), worker_tags=("linux",))
    assert is_eligible(["prod"], ["linux"], [r]) is True


def test_is_eligible_single_rule_fails() -> None:
    r = _rule(device_tags=("prod",), worker_tags=("linux",))
    assert is_eligible(["prod"], ["macos"], [r]) is False


def test_is_eligible_multiple_rules_all_must_pass() -> None:
    r_kitchen = _rule(device_tags=("kitchen",), worker_tags=("kitchen",))
    r_prod = _rule(device_tags=("prod",), worker_tags=("linux",))
    # Device with both tags; worker has only kitchen → second rule fails.
    assert is_eligible(["kitchen", "prod"], ["kitchen"], [r_kitchen, r_prod]) is False
    # Worker has both → both rules pass.
    assert is_eligible(["kitchen", "prod"], ["kitchen", "linux"], [r_kitchen, r_prod]) is True


def test_is_eligible_inapplicable_rules_dont_block() -> None:
    """A rule whose device_match doesn't hold doesn't disqualify the worker."""
    r = _rule(device_tags=("kitchen",), worker_tags=("kitchen",))
    assert is_eligible(["office"], ["windows"], [r]) is True


# ---------------------------------------------------------------------------
# RoutingRuleStore — persistence
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> RoutingRuleStore:
    return RoutingRuleStore(path=tmp_path / "routing-rules.json")


def test_store_starts_empty(store: RoutingRuleStore) -> None:
    assert store.list_rules() == []


def test_store_create_lists_and_persists(tmp_path: Path) -> None:
    s1 = RoutingRuleStore(path=tmp_path / "rules.json")
    s1.create_rule(Rule(
        id="kitchen-only",
        name="Kitchen only",
        severity="required",
        device_match=[Clause(op="all_of", tags=["kitchen"])],
        worker_match=[Clause(op="all_of", tags=["kitchen"])],
    ))
    assert [r.id for r in s1.list_rules()] == ["kitchen-only"]
    # Persistence: re-load picks up the rule.
    s2 = RoutingRuleStore(path=tmp_path / "rules.json")
    assert [r.id for r in s2.list_rules()] == ["kitchen-only"]


def test_store_update_replaces(store: RoutingRuleStore) -> None:
    store.create_rule(Rule(
        id="r1", name="r1", severity="required",
        device_match=[Clause(op="all_of", tags=["a"])],
        worker_match=[Clause(op="all_of", tags=["a"])],
    ))
    store.update_rule("r1", Rule(
        id="r1", name="renamed", severity="required",
        device_match=[Clause(op="all_of", tags=["b"])],
        worker_match=[Clause(op="all_of", tags=["b"])],
    ))
    rules = store.list_rules()
    assert len(rules) == 1
    assert rules[0].name == "renamed"
    assert rules[0].device_match[0].tags == ["b"]


def test_store_delete(store: RoutingRuleStore) -> None:
    store.create_rule(Rule(
        id="r1", name="r1", severity="required",
        device_match=[Clause(op="all_of", tags=["a"])],
        worker_match=[Clause(op="all_of", tags=["a"])],
    ))
    assert store.delete_rule("r1") is True
    assert store.list_rules() == []
    # Deleting a missing id is a no-op that returns False.
    assert store.delete_rule("nope") is False


def test_store_create_rejects_duplicate_id(store: RoutingRuleStore) -> None:
    r = Rule(
        id="r1", name="r1", severity="required",
        device_match=[Clause(op="all_of", tags=["a"])],
        worker_match=[Clause(op="all_of", tags=["a"])],
    )
    store.create_rule(r)
    with pytest.raises(RoutingRuleError):
        store.create_rule(r)


def test_store_create_rejects_non_required_severity(store: RoutingRuleStore) -> None:
    with pytest.raises(RoutingRuleError):
        store.create_rule(Rule(
            id="r1", name="r1", severity="preferred",  # type: ignore[arg-type]
            device_match=[Clause(op="all_of", tags=["a"])],
            worker_match=[Clause(op="all_of", tags=["a"])],
        ))


def test_store_create_rejects_empty_clause_tags(store: RoutingRuleStore) -> None:
    with pytest.raises(RoutingRuleError):
        store.create_rule(Rule(
            id="r1", name="r1", severity="required",
            device_match=[Clause(op="all_of", tags=[])],
            worker_match=[Clause(op="all_of", tags=["a"])],
        ))


def test_store_create_rejects_unknown_operator(store: RoutingRuleStore) -> None:
    with pytest.raises(RoutingRuleError):
        store.create_rule(Rule(
            id="r1", name="r1", severity="required",
            device_match=[Clause(op="includes", tags=["a"])],  # type: ignore[arg-type]
            worker_match=[Clause(op="all_of", tags=["a"])],
        ))


def test_store_corrupt_file_loads_empty(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text("{not valid json")
    s = RoutingRuleStore(path=path)
    assert s.list_rules() == []


def test_store_unknown_schema_version_loads_empty(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"version": 999, "rules": []}))
    s = RoutingRuleStore(path=path)
    assert s.list_rules() == []


# ---------------------------------------------------------------------------
# Effective rules: global + per-device routing_extra
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TG.4 helpers — slugify + body parser used by the UI API endpoints
# ---------------------------------------------------------------------------


def test_slugify_basic() -> None:
    from ui_api import _slugify
    assert _slugify("Kitchen Devices Need Kitchen Worker") == "kitchen-devices-need-kitchen-worker"


def test_slugify_collapses_runs_and_trims() -> None:
    from ui_api import _slugify
    assert _slugify("  --  Hello   World  __  ") == "hello-world"


def test_slugify_drops_punctuation() -> None:
    from ui_api import _slugify
    assert _slugify("My Rule (v2)!") == "my-rule-v2"


def test_slugify_empty_for_empty_input() -> None:
    from ui_api import _slugify
    assert _slugify("") == ""
    assert _slugify("!!!") == ""


def test_parse_rule_auto_slugs_id() -> None:
    from ui_api import _parse_rule
    rule = _parse_rule({
        "name": "Kitchen only",
        "device_match": [{"op": "all_of", "tags": ["kitchen"]}],
        "worker_match": [{"op": "all_of", "tags": ["kitchen"]}],
    })
    assert rule.id == "kitchen-only"
    assert rule.name == "Kitchen only"
    assert rule.severity == "required"


def test_parse_rule_explicit_id_wins() -> None:
    from ui_api import _parse_rule
    rule = _parse_rule({
        "id": "custom-id",
        "name": "Kitchen only",
        "device_match": [{"op": "all_of", "tags": ["kitchen"]}],
        "worker_match": [{"op": "all_of", "tags": ["kitchen"]}],
    })
    assert rule.id == "custom-id"


def test_parse_rule_default_id_used_when_no_id_or_name_slug() -> None:
    """Update path passes default_id=path_param so an empty/non-slug-able
    name doesn't lose the rule id mid-update."""
    from ui_api import _parse_rule
    rule = _parse_rule({"name": "!!!"}, default_id="path-id")
    assert rule.id == "path-id"


def test_parse_rule_rejects_missing_name() -> None:
    from ui_api import _parse_rule
    with pytest.raises(RoutingRuleError):
        _parse_rule({})


def test_parse_rule_rejects_non_required_severity() -> None:
    from ui_api import _parse_rule
    with pytest.raises(RoutingRuleError):
        _parse_rule({
            "name": "n",
            "severity": "preferred",
            "device_match": [{"op": "all_of", "tags": ["a"]}],
            "worker_match": [{"op": "all_of", "tags": ["a"]}],
        })


def test_effective_rules_compose_global_with_device_extra() -> None:
    """``effective_rules = global + device.routing_extra`` — strictly additive."""
    global_rules = [_rule(device_tags=("kitchen",), worker_tags=("kitchen",))]
    # device-specific extra rule: this device additionally needs a worker
    # with the "fast" tag (regardless of any device tag matcher).
    extra_rule = Rule(
        id="",  # inline rules have no id; fine — they can't be referenced
        name="device-only-fast",
        severity="required",
        device_match=[Clause(op="any_of", tags=["kitchen", "office"])],
        worker_match=[Clause(op="all_of", tags=["fast"])],
    )
    rules = global_rules + [extra_rule]
    # Worker has kitchen but not fast → device-extra rule blocks.
    assert is_eligible(["kitchen"], ["kitchen"], rules) is False
    # Worker has both → both rules pass.
    assert is_eligible(["kitchen"], ["kitchen", "fast"], rules) is True
