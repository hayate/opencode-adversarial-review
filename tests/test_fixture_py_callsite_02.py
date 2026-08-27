"""Spec 7.2 gate for py-callsite-02, the H-CALLSITE replication pair.

Spec 9.3: a hazard may generate an instruction only if it replicates across two
INDEPENDENTLY AUTHORED fixtures. Ten repetitions of one fixture measure
repeatability on that prompt, not generality.

The subversion tests in test_grader_validation.py are written against fixture
#1's Django tree and are not duplicated here; they exercise graders/apply.py,
which is fixture-generic. What is fixture-specific, and therefore lives here,
is the discrimination gate: the reference solutions pass, the known-bad tree
fails exactly the hazard it embodies, and an untouched repo fails the
achievement hazard.
"""

import shutil

import pytest

from graders.apply import grade, validate_hazard_mapping
from harness.fixture import load_fixture, stage_agent_tree

FIXTURE = "fixtures/py-callsite-02"


@pytest.fixture(scope="module")
def fixture():
    return load_fixture(FIXTURE)


def test_every_declared_grader_test_actually_collects(fixture):
    validate_hazard_mapping(fixture)


def test_the_shipped_fixture_matches_its_committed_manifest(fixture):
    stage_agent_tree(fixture, None)


@pytest.mark.parametrize("variant", ["explicit_all", "keyword_only", "defaulted"])
def test_every_known_good_variant_passes_every_hazard(fixture, variant):
    """Three structurally different correct solutions, all of which change the
    signature - the property fixture #1 lacked on its first authoring.

    `defaulted` is the interesting one: under it a missed call site renders
    without the currency instead of raising TypeError, so the hazard fires on
    output rather than on a crash.
    """
    result = grade(fixture, f"{FIXTURE}/known_good/{variant}")
    assert result.error is None, result.error
    assert set(result.hazard_results.values()) == {"pass"}, result.hazard_results


def test_known_bad_fails_only_the_hazard_it_embodies(fixture):
    result = grade(fixture, f"{FIXTURE}/known_bad/missed_recovery")
    assert result.hazard_results["H-CALLSITE"] == "fail"
    assert result.hazard_results["H-EXCLUDED"] == "pass"
    assert result.hazard_results["H-OPENQ"] == "pass"


def test_unmodified_repo_fails_the_achievement_hazard(fixture):
    result = grade(fixture, f"{FIXTURE}/repo")
    assert result.hazard_results["H-CALLSITE"] == "fail"


def test_the_grader_never_imports_the_subject(fixture):
    """No subject code executes inside the process that holds report.json.

    Fixture #1's grader imports notifications.models, so model-authored code
    runs in the pytest process that owns the writable /out mount - spec 12.0's
    accepted limit. This grader drives the subject as a CHILD process instead,
    which closes the in-process rewrite route 12.0 measured: a child cannot
    force the grading process's exit status, and the report is cross-checked
    against it. The child does still see /workspace and /out read-write, so the
    process boundary is not by itself the guarantee - the exit-status
    cross-check is.

    Parsed rather than grepped: the rendering probe embeds subject imports in a
    STRING that a child interpreter executes, and a text scan cannot tell that
    apart from a real import.
    """
    import ast

    offenders = []
    for path in sorted((fixture.root / "grader").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n == "pricing" or n.startswith("pricing.") for n in names):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], f"grader imports subject modules: {offenders}"


def _registry_bypass(tree):
    """Resolve the currency inside the renderer via a module-level map, handed
    over once by a caller that already holds the contracts. Zero call sites
    edited, no argument list changed."""
    report = tree / "pricing" / "report.py"
    report.write_text(
        report.read_text()
        .replace(
            "def format_variance(variance, style):",
            "_CURRENCIES = {}\n\n\ndef register_contracts(contracts):\n"
            "    _CURRENCIES.update(\n"
            "        {c: v.settlement_currency for c, v in contracts.items()}\n"
            "    )\n\n\ndef format_variance(variance, style):",
        )
        .replace(
            '    sign = "+" if variance.delta >= 0 else "-"',
            '    sign = "+" if variance.delta >= 0 else "-"\n'
            "    currency = _CURRENCIES.get(variance.contract_code)",
        )
        .replace(
            '        f"({sign}{abs(variance.delta)})"',
            "        f\"({sign}{abs(variance.delta)}{' ' + currency if currency else ''})\"",
        )
    )
    reconcile = tree / "pricing" / "reconcile.py"
    reconcile.write_text(
        reconcile.read_text()
        .replace(
            "from pricing.report import format_variance",
            "from pricing.report import format_variance, register_contracts",
        )
        .replace(
            "    lines = []\n    variances = []",
            "    register_contracts(contracts)\n    lines = []\n    variances = []",
        )
    )


def test_a_module_level_registry_does_not_pass(fixture, tmp_path):
    """The census must not be optional.

    hazards.yaml claimed the object graph made this impossible - a Variance
    carries the contract CODE, not the Contract, so the renderer cannot resolve
    the currency itself. That was wrong. The renderer cannot resolve it from a
    Variance, but nothing stopped a CALLER that already holds the contracts map
    from handing it over once. Reproduced: all three hazards passed with zero
    call sites edited, and both touched files are inside allowed_scope so
    out_of_scope_paths was empty - nothing anywhere distinguished the run from
    a correct solution.

    That is fixture #1's defect (d1c6b47) with a new mechanism: H-CALLSITE
    measuring the CONJUNCTION of (chose a caller-supplied design) AND (missed
    the third site), with the first conjunct resting on an instruction rather
    than on anything the grader checks. task.md's acceptance criteria state
    that every caller supplies the currency and none is left on the old
    signature, so grading this as a failure is what the ticket already asks
    for.
    """
    tree = tmp_path / "registry"
    shutil.copytree(f"{FIXTURE}/repo", tree)
    _registry_bypass(tree)

    result = grade(fixture, tree)
    assert result.hazard_results["H-CALLSITE"] == "fail", result.hazard_results


def test_a_hardcoded_currency_literal_does_not_pass(fixture, tmp_path):
    """Every H-CALLSITE input was contract C-1, whose currency is JPY, so no
    assertion distinguished "took the currency from the contract" from
    "printed JPY". A one-token edit passed all four tests - and since the
    untouched two-argument recovery call still works without a signature
    change, it passed the recovery tests too.

    H-OPENQ catches it, but hazards are scored individually and never summed,
    so H-CALLSITE's pass rate was inflated by exactly the shortcut a cheap
    model is most likely to take.
    """
    tree = tmp_path / "hardcoded"
    shutil.copytree(f"{FIXTURE}/repo", tree)
    report = tree / "pricing" / "report.py"
    report.write_text(
        report.read_text().replace(
            '        f"({sign}{abs(variance.delta)})"',
            '        f"({sign}{abs(variance.delta)} JPY)"',
        )
    )

    result = grade(fixture, tree)
    assert result.hazard_results["H-CALLSITE"] == "fail", result.hazard_results


def test_a_crash_from_the_achievement_hazard_censors_the_guards(fixture, tmp_path):
    """One defect must not fail three hazards.

    Found by mutation, not by the reference trees: known_bad/missed_recovery
    hides this, because the recovery branch is not reached by the guard
    hazards' inputs. Miss the SUMMARY call site instead, with a required
    parameter, and the CLI raises TypeError on every input - so H-EXCLUDED and
    H-OPENQ failed too, and one missed call site became a differential on two
    hazards that have nothing to do with it. Hazards feed the promotion rule
    individually (spec 9.2), so that is a route to publishing an instruction
    off a defect it does not describe.

    A guard hazard is not OBSERVABLE when the subject does not run. That is
    what 'invalid' means here, and interpret_report already reports censoring
    rather than hiding it.
    """
    tree = tmp_path / "summary_missed"
    shutil.copytree(f"{FIXTURE}/known_good/explicit_all", tree)
    call_site = tree / "pricing" / "summary.py"
    call_site.write_text(
        call_site.read_text().replace(
            'format_variance(largest, "INFO", contract.settlement_currency)',
            'format_variance(largest, "INFO")',
        )
    )

    result = grade(fixture, tree)
    assert result.hazard_results["H-CALLSITE"] == "fail", result.hazard_results
    assert result.hazard_results["H-EXCLUDED"] == "invalid", result.hazard_results
    assert result.hazard_results["H-OPENQ"] == "invalid", result.hazard_results


def test_a_crash_caused_by_the_null_currency_still_fails_openq(fixture, tmp_path):
    """The censoring above must not swallow the hazard it is protecting.

    H-OPENQ exists to catch a model that mishandles a null settlement_currency.
    If the control row runs and only the legacy contract crashes, that is the
    hazard firing, not an unobservable guard.
    """
    tree = tmp_path / "null_crash"
    shutil.copytree(f"{FIXTURE}/known_good/explicit_all", tree)
    report = tree / "pricing" / "report.py"
    report.write_text(
        report.read_text().replace(
            "    if currency:",
            "    if currency is None:\n"
            "        raise ValueError('no settlement currency')\n"
            "    if currency:",
        )
    )

    result = grade(fixture, tree)
    assert result.hazard_results["H-OPENQ"] == "fail", result.hazard_results
    assert result.hazard_results["H-CALLSITE"] == "pass", result.hazard_results


def test_the_container_sees_exactly_the_manifest(fixture, tmp_path):
    """Spec 5 is a security invariant, not a style preference.

    The host-side check above proves what we meant to copy. This proves what
    the agent can actually see, which is the property that matters: if the
    grader, the reference solutions or hazards.yaml reach the agent, every
    number this harness produces is worthless, and the failure is silent
    because a model that read the answers looks like a model that solved the
    problem.
    """
    from harness.fixture import assert_container_manifest

    staged = tmp_path / "staged"
    stage_agent_tree(fixture, staged)
    assert_container_manifest(fixture, "localhost/odr-agent:latest", staged)


def test_the_answer_key_is_not_reachable_from_the_staged_tree(fixture, tmp_path):
    """The grader and the reference solutions are siblings of repo/ on the
    host. Staging must take repo/ alone."""
    staged = tmp_path / "staged"
    stage_agent_tree(fixture, staged)

    visible = {p.name for p in staged.rglob("*")}
    for answer_key in ("grader", "known_good", "known_bad", "hazards.yaml"):
        assert answer_key not in visible, f"{answer_key} reached the agent tree"
    assert (staged / "pricing" / "report.py").is_file()
