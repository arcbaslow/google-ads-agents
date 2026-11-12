"""Review and validate the exact operations before sending a write."""

from __future__ import annotations

import copy
import json
import sys

from google.api_core import exceptions as api_errors
from google.protobuf.json_format import MessageToDict

# Without a client deadline a hung mutate never returns.
WRITE_TIMEOUT_SECONDS = 60


class MutationCancelled(RuntimeError):
    """The operator did not explicitly approve the displayed request."""


class MutationOutcomeUnknown(RuntimeError):
    """The apply request was sent without a confirmed result."""


def review_request(preview: dict, action: str) -> None:
    print(json.dumps(preview, indent=2), file=sys.stderr)
    print(f"{action} these operations? y/N", file=sys.stderr, flush=True)
    if not sys.stdin.isatty():
        raise MutationCancelled("Mutation cancelled; review it in an interactive terminal")
    try:
        approved = input().strip().lower() == "y"
    except (EOFError, OSError):
        approved = False
    if not approved:
        raise MutationCancelled("Mutation cancelled; explicit y confirmation is required")


def reviewed_mutate(mutation, *, customer_id: str, operations: list,
                    validate_only: bool):
    """Preview, confirm, validate, then optionally apply the same operations.

    This boundary applies to Python callers as well as the CLI. There is no
    automatic approval option. Validation failures propagate without a write.
    """
    reviewed = copy.deepcopy(operations)
    preview = {
        "customer_id": customer_id,
        "operations": [MessageToDict(op._pb, preserving_proto_field_name=True)
                       for op in reviewed],
        "validate_only": validate_only,
    }
    action = "Validate only" if validate_only else "Validate, then apply"
    review_request(preview, action)

    def send(validate):
        # validate_only exists only on the request message, not as a method keyword.
        return mutation(request={"customer_id": customer_id,
                                 "operations": copy.deepcopy(reviewed),
                                 "validate_only": validate},
                        timeout=WRITE_TIMEOUT_SECONDS)

    response = send(True)
    if validate_only:
        return response
    from google.ads.googleads.errors import GoogleAdsException

    try:
        return send(False)
    except (api_errors.DeadlineExceeded, api_errors.ServiceUnavailable,
            api_errors.InternalServerError) as exc:
        raise MutationOutcomeUnknown("Apply was sent; no confirmed result") from exc
    except GoogleAdsException as exc:
        # Writes carry no idempotency key, so an internal error is treated as unknown.
        if any(e.error_code._pb.WhichOneof("error_code") == "internal_error"
               for e in exc.failure.errors):
            raise MutationOutcomeUnknown("Apply was sent; Google Ads reported an internal error") from exc
        raise


def reviewed_atomic_mutate(client, customer_id: str, operations: list, validate_only: bool):
    """Use GoogleAdsService for linked resources, without partial writes or retries."""
    service = client.get_service("GoogleAdsService")

    def send(*, request, timeout):
        return service.mutate(
            request={"customer_id": request["customer_id"],
                     "mutate_operations": request["operations"],
                     "validate_only": request["validate_only"], "partial_failure": False},
            retry=None, timeout=timeout)

    print("Atomic request: partial_failure=false; automatic retries disabled.", file=sys.stderr)
    return reviewed_mutate(send, customer_id=customer_id, operations=operations,
                           validate_only=validate_only)
