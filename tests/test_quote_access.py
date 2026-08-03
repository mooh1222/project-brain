from project_brain.quote_access import (
    AccessState,
    QuoteAccess,
    evaluate_quote_access,
)
from project_brain.store import BrainStore


def _store(*objects: dict) -> BrainStore:
    return BrainStore({obj["id"]: obj for obj in objects})


def _locator() -> dict:
    return {"id": "code.ctx.anchor", "kind": "CodeLocator"}


def _manifest(*, redaction_status: str = "approved") -> dict:
    return {
        "id": "manifest.ctx.source",
        "kind": "EvidenceManifest",
        "redaction_status": redaction_status,
        "acl": ["team"],
    }


def _evidence_ref(*, manifest_id: str = "manifest.ctx.source") -> dict:
    return {
        "id": "evref.ctx.anchor",
        "kind": "EvidenceRef",
        "evidence_manifest_id": manifest_id,
        "locator": {"code_locator_id": "code.ctx.anchor"},
    }


def test_reverse_evidence_ref_and_approved_manifest_allow_quote():
    result = evaluate_quote_access(
        "code.ctx.anchor",
        _store(_locator(), _manifest(), _evidence_ref()),
        principal={"teams": ["team"]},
        acl_evaluator=lambda _principal, _manifest: AccessState.ALLOW,
    )

    assert result == QuoteAccess(
        redaction=AccessState.ALLOW,
        principal_acl=AccessState.ALLOW,
        final=AccessState.ALLOW,
    )


def test_nonapproved_manifest_denies_even_when_acl_allows():
    result = evaluate_quote_access(
        "code.ctx.anchor",
        _store(
            _locator(),
            _manifest(redaction_status="staged"),
            _evidence_ref(),
        ),
        principal={"teams": ["team"]},
        acl_evaluator=lambda _principal, _manifest: AccessState.ALLOW,
    )

    assert result.redaction is AccessState.DENY
    assert result.principal_acl is AccessState.ALLOW
    assert result.final is AccessState.DENY


def test_missing_manifest_is_indeterminate_and_does_not_call_acl():
    calls = []

    result = evaluate_quote_access(
        "code.ctx.anchor",
        _store(_locator(), _evidence_ref(manifest_id="manifest.ctx.missing")),
        principal={"teams": ["team"]},
        acl_evaluator=lambda principal, manifest: calls.append(
            (principal, manifest)
        ),
    )

    assert result == QuoteAccess(
        redaction=AccessState.INDETERMINATE,
        principal_acl=AccessState.INDETERMINATE,
        final=AccessState.INDETERMINATE,
    )
    assert calls == []


def test_missing_principal_keeps_approved_redaction_but_omits_quote():
    result = evaluate_quote_access(
        "code.ctx.anchor",
        _store(_locator(), _manifest(), _evidence_ref()),
        principal=None,
        acl_evaluator=lambda _principal, _manifest: AccessState.ALLOW,
    )

    assert result == QuoteAccess(
        redaction=AccessState.ALLOW,
        principal_acl=AccessState.INDETERMINATE,
        final=AccessState.INDETERMINATE,
    )


def test_acl_evaluator_error_is_indeterminate_and_omits_quote():
    def broken_evaluator(_principal, _manifest):
        raise RuntimeError("identity service unavailable")

    result = evaluate_quote_access(
        "code.ctx.anchor",
        _store(_locator(), _manifest(), _evidence_ref()),
        principal={"teams": ["team"]},
        acl_evaluator=broken_evaluator,
    )

    assert result == QuoteAccess(
        redaction=AccessState.ALLOW,
        principal_acl=AccessState.INDETERMINATE,
        final=AccessState.INDETERMINATE,
    )


def test_no_reverse_evidence_ref_is_indeterminate():
    assert evaluate_quote_access(
        "code.ctx.anchor",
        _store(_locator()),
        principal={"teams": ["team"]},
        acl_evaluator=lambda _principal, _manifest: AccessState.ALLOW,
    ) == QuoteAccess(
        redaction=AccessState.INDETERMINATE,
        principal_acl=AccessState.INDETERMINATE,
        final=AccessState.INDETERMINATE,
    )
