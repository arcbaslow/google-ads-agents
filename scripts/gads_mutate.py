"""Review and validate the exact operations before sending a write."""

from __future__ import annotations

import copy
import json
import sys

from google.protobuf.json_format import MessageToDict


class MutationCancelled(RuntimeError):
    """The operator did not explicitly approve the displayed request."""


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
    print(json.dumps(preview, indent=2), file=sys.stderr)
    action = "Validate only" if validate_only else "Validate, then apply"
    print(f"{action} these operations? y/N", file=sys.stderr, flush=True)
    try:
        approved = input().strip().lower() == "y"
    except (EOFError, OSError):
        approved = False
    if not approved:
        raise MutationCancelled("Mutation cancelled; explicit y confirmation is required")

    response = mutation(customer_id=customer_id, operations=copy.deepcopy(reviewed),
                        validate_only=True)
    if validate_only:
        return response
    return mutation(customer_id=customer_id, operations=copy.deepcopy(reviewed),
                    validate_only=False)


def reviewed_atomic_mutate(client, customer_id: str, operations: list, validate_only: bool):
    """Use GoogleAdsService for linked resources, without partial writes or retries."""
    service = client.get_service("GoogleAdsService")

    def send(*, customer_id, operations, validate_only):
        return service.mutate(customer_id=customer_id, mutate_operations=operations,
                              validate_only=validate_only, partial_failure=False, retry=None)

    print("Atomic request: partial_failure=false; automatic retries disabled.", file=sys.stderr)
    return reviewed_mutate(send, customer_id=customer_id, operations=operations,
                           validate_only=validate_only)
