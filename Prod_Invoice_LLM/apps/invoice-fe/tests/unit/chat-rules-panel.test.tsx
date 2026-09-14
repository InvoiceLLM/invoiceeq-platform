/**
 * FE Gap 478 — the Chat Rules panel renders whatever the API returns, gates the
 * delete affordance on `can_train`, and explains where rules come from when
 * there are none.
 *
 * Every assertion here is a property of the render, not a fixture's literal
 * output: rule rows are compared against the fixture the test itself mutates
 * (rules renamed, category swapped for one the vocabulary has never heard of,
 * a row added, the author dropped), so a hardcoded label or a hardcoded
 * category map fails the test rather than passing it.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import ChatRulesPanel, {
  chatRuleCategoryLabel,
  formatChatRuleAddedAt,
} from "@/components/settings/ChatRulesPanel";
import type { ChatRule } from "@/lib/chat-training-service";

const categoryLabels = {
  wrong_direction: "Wrong invoice direction",
  should_have_included: "Should have been included",
};

const baseRules: ChatRule[] = [
  {
    id: "rule-a",
    category: "wrong_direction",
    pattern: "payables",
    ruleText: "When asked what we owe, count payables only.",
    enabled: true,
    createdBy: "ops@example.test",
    createdAt: "2026-09-09T10:15:00Z",
  },
  {
    id: "rule-b",
    category: "should_have_included",
    pattern: "",
    ruleText: "Include credit notes when totalling a supplier balance.",
    enabled: true,
    createdAt: null,
  },
];

describe("ChatRulesPanel (FE Gap 478)", () => {
  it("renders one row per rule, carrying the API's own text, label, timestamp and author", () => {
    const { getAllByTestId, queryAllByTestId } = render(
      <ChatRulesPanel rules={baseRules} categoryLabels={categoryLabels} canTrain />
    );

    const rows = getAllByTestId("chat-rule-row");
    expect(rows).toHaveLength(baseRules.length);
    rows.forEach((row, index) => {
      const rule = baseRules[index];
      expect(row.getAttribute("data-rule-id")).toBe(rule.id);
      expect(row.textContent).toContain(rule.ruleText);
      expect(row.textContent).toContain(
        categoryLabels[rule.category as keyof typeof categoryLabels]
      );
    });

    // Author renders only where the API carried one.
    expect(queryAllByTestId("chat-rule-author")).toHaveLength(
      baseRules.filter((rule) => rule.createdBy).length
    );
    // Timestamps: every row states when it was added, nullable one included.
    expect(queryAllByTestId("chat-rule-added-at")).toHaveLength(baseRules.length);
    expect(getAllByTestId("chat-rule-added-at")[1].textContent).toContain("Date unknown");
  });

  it("survives a mutated fixture — renamed rules, an unknown category, an extra row", () => {
    const mutated: ChatRule[] = [
      {
        ...baseRules[0],
        id: "rule-z",
        // A category the vocabulary in this test has never heard of: the label
        // must still be derived, never looked up in a table inside the FE.
        category: "supplier_alias_mismatch",
        ruleText: "Treat 'ACME Pvt Ltd' and 'ACME Private Limited' as one supplier.",
        createdBy: undefined,
      },
      ...baseRules,
    ];

    const { getAllByTestId, queryAllByTestId } = render(
      <ChatRulesPanel rules={mutated} categoryLabels={categoryLabels} canTrain />
    );

    const rows = getAllByTestId("chat-rule-row");
    expect(rows).toHaveLength(mutated.length);
    expect(rows.map((row) => row.getAttribute("data-rule-id"))).toEqual(
      mutated.map((rule) => rule.id)
    );
    rows.forEach((row, index) => {
      expect(row.textContent).toContain(mutated[index].ruleText);
    });
    expect(getAllByTestId("chat-rule-category")[0].textContent).toBe(
      "Supplier alias mismatch"
    );
    expect(queryAllByTestId("chat-rule-author")).toHaveLength(
      mutated.filter((rule) => rule.createdBy).length
    );
  });

  it("hides delete entirely without can_train, and says why", () => {
    const { queryAllByTestId, getByTestId } = render(
      <ChatRulesPanel
        rules={baseRules}
        categoryLabels={categoryLabels}
        canTrain={false}
        onDelete={vi.fn()}
      />
    );
    expect(queryAllByTestId("chat-rule-delete")).toHaveLength(0);
    expect(getByTestId("chat-rules-readonly")).toBeTruthy();
    // The rules themselves stay readable — read-only, not hidden.
    expect(queryAllByTestId("chat-rule-row")).toHaveLength(baseRules.length);
  });

  it("shows one delete per rule with can_train, and no read-only notice", () => {
    const { queryAllByTestId, queryByTestId } = render(
      <ChatRulesPanel
        rules={baseRules}
        categoryLabels={categoryLabels}
        canTrain
        onDelete={vi.fn()}
      />
    );
    expect(queryAllByTestId("chat-rule-delete")).toHaveLength(baseRules.length);
    expect(queryByTestId("chat-rules-readonly")).toBeNull();
  });

  it("deletes only the confirmed rule, and reports the rule it was clicked on", () => {
    const onDelete = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { getAllByTestId } = render(
      <ChatRulesPanel
        rules={baseRules}
        categoryLabels={categoryLabels}
        canTrain
        onDelete={onDelete}
      />
    );

    fireEvent.click(getAllByTestId("chat-rule-delete")[1]);
    expect(confirmSpy).toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    fireEvent.click(getAllByTestId("chat-rule-delete")[1]);
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith(baseRules[1]);
  });

  it("disables only the row whose delete is in flight", () => {
    const { getAllByTestId } = render(
      <ChatRulesPanel
        rules={baseRules}
        categoryLabels={categoryLabels}
        canTrain
        deletingId={baseRules[0].id}
        onDelete={vi.fn()}
      />
    );
    const buttons = getAllByTestId("chat-rule-delete") as HTMLButtonElement[];
    expect(buttons[0].disabled).toBe(true);
    expect(buttons[1].disabled).toBe(false);
  });

  it("explains where rules come from when there are none", () => {
    const { getByTestId, queryByTestId } = render(
      <ChatRulesPanel rules={[]} canTrain onDelete={vi.fn()} />
    );
    const empty = getByTestId("chat-rules-empty");
    expect(empty.textContent).toContain("thumbs-down");
    expect(queryByTestId("chat-rules-list")).toBeNull();
    expect(queryByTestId("chat-rule-delete")).toBeNull();
  });
});

describe("chatRuleCategoryLabel / formatChatRuleAddedAt (FE Gap 478)", () => {
  it("prefers the backend vocabulary and humanises anything it does not carry", () => {
    expect(chatRuleCategoryLabel("wrong_direction", categoryLabels)).toBe(
      categoryLabels.wrong_direction
    );
    expect(chatRuleCategoryLabel("a_brand_new_category", categoryLabels)).toBe(
      "A brand new category"
    );
    expect(chatRuleCategoryLabel("", categoryLabels)).toBe("Uncategorised");
    expect(chatRuleCategoryLabel("wrong_direction", { wrong_direction: "  " })).toBe(
      "Wrong direction"
    );
  });

  it("never renders an unusable timestamp", () => {
    expect(formatChatRuleAddedAt(null)).toBe("Date unknown");
    expect(formatChatRuleAddedAt(undefined)).toBe("Date unknown");
    expect(formatChatRuleAddedAt("not-a-date")).toBe("Date unknown");
    const rendered = formatChatRuleAddedAt("2026-09-09T10:15:00Z");
    expect(rendered).not.toBe("Date unknown");
    expect(rendered).toContain("2026");
  });
});
