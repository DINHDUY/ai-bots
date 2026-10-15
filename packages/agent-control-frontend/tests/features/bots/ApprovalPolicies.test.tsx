import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";
import { server } from "../../support/server";
import { ApprovalPolicies, SaveApprovalPolicy } from "../../../src/features/bots/ApprovalPolicies";

it("creates an explicit server rule and revokes it without approving a pending action", async () => {
  const requests: string[] = [];
  const policies: any[] = [];
  server.use(
    http.get("*/api/bots/bot/approval-policies", () =>
      HttpResponse.json(policies),
    ),
    http.post("*/api/bots/bot/approval-policies", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      requests.push("create");
      expect(body.approval_id).toBe("approval_1");
      expect(body.ttl_seconds).toBe(3600);
      expect(body.request_id).toBeTruthy();
      const policy = {
        id: "policy_1",
        operation: "bash",
        summary: "Exact shell text; pinned workspace",
        status: "active",
        version: 1,
        expires_at: "2026-10-08T12:00:00Z",
      };
      policies.push(policy);
      return HttpResponse.json(policy, { status: 201 });
    }),
    http.post("*/api/bots/bot/approval-policies/policy_1/revoke", () => {
      requests.push("revoke");
      policies[0].status = "revoked";
      policies[0].version = 2;
      return HttpResponse.json(policies[0]);
    }),
  );
  const user = userEvent.setup();
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SaveApprovalPolicy
        botId="bot"
        approvalId="approval_1"
        scope="Exact shell text; workspace revision abc"
      />
      <ApprovalPolicies botId="bot" />
    </QueryClientProvider>,
  );
  const rules = await screen.findByText("Server approval rules (0)");
  expect(rules.closest("details")).not.toHaveAttribute("open");
  await user.click(rules);
  expect(screen.getByText("No saved rules. Actions require approval.")).toBeVisible();
  await user.click(screen.getByText("Save an approval rule"));
  await user.selectOptions(screen.getByLabelText("Rule duration"), "3600");
  await user.click(screen.getByRole("button", { name: "Save rule" }));
  await screen.findByRole("button", { name: "Rule saved" });
  const rule = await screen.findByText("bash · active");
  expect(rule.closest("details")).not.toHaveAttribute("open");
  await user.click(rule);
  await user.click(await screen.findByRole("button", { name: "Revoke rule" }));
  await screen.findByText("bash · revoked");
  expect(requests).toEqual(["create", "revoke"]);
});
