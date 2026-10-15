from __future__ import annotations

from typing import TYPE_CHECKING

from agentbot_control.event_store import stamp
from agentbot_control.providers.azure import CloudError

if TYPE_CHECKING:
    from agentbot_control.cloud import CloudComputers


async def step(self: CloudComputers, op):
    binding = self.binding(binding_id=op["binding_id"])
    if not binding:
        return self.finish(
            op,
            "failed",
            "Inventory is missing; manual investigation required.",
            "inventory_missing",
        )
    if op["deadline"] < stamp():
        self.quarantine(
            binding["id"],
            "Lifecycle deadline expired; resource outcome must be inspected",
        )
        return self.finish(
            op,
            "outcome_unknown",
            "Deadline expired. The original resource remains tracked; no request was replayed.",
            "deadline_exceeded",
        )
    operation, phase = op["operation"], op["phase"]
    driver, profile = self.driver(binding), self.profile_for(binding)
    try:
        if phase == "reserved":
            # Recheck membership/grant before a queued paid operation starts.
            return await provisioning.reserved(self, op, binding, operation, driver, profile)
        if phase == "bootstrap":
            return await provisioning.bootstrap(self, op, binding, operation, driver, profile)
        if phase in {"submitting", "polling"}:
            # On restart or response loss, inspect the same target. Never resubmit.
            return await reconciliation.polling(self, op, binding, operation, driver, profile)
        if phase == "connecting":
            return await reconciliation.connecting(self, op, binding, operation, driver, profile)
        if phase in {"ensuring", "verifying"}:
            return await reconciliation.verifying(self, op, binding, operation, driver, profile)
        if phase == "resetting":
            return await reconciliation.resetting(self, op, binding, operation, driver, profile)
    except CloudError as exc:
        current = self.operation(op["operation_id"])
        if current["phase"] in {"submitting", "polling"} or exc.code in {
            "azure_throttled",
            "azure_unavailable",
        }:
            self.update(op, detail=str(exc), error_code=exc.code, delay=exc.retry_after)
        else:
            self.finish(op, "failed", str(exc), exc.code)
    except Exception:
        current = self.operation(op["operation_id"])
        if current["phase"] in {"submitting", "polling", "connecting", "verifying"}:
            self.update(
                op,
                detail="Waiting for a verifiable Azure or host response. The operation remains tracked.",
            )
        else:
            self.quarantine(binding["id"], "Lifecycle response could not be confirmed")
            self.finish(
                op,
                "outcome_unknown",
                "Lifecycle response could not be confirmed. No action will be replayed.",
                "response_unknown",
            )


from agentbot_control.cloud import provisioning, reconciliation
