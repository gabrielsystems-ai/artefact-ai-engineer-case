# Online return-policy clarification

## Purpose

Demonstrate policy retrieval and clarification before individual return eligibility is determined.

## Conversation

**Customer**

I bought an item online and want to return it. Can I return it?

**Assistant**

According to the store’s policy, online purchases can be returned within **7 calendar days after receipt**, without giving a reason. The item should be unused, in its original packaging, with all accessories and manuals. The store covers return shipping for this type of return.

When did you actually receive the item? Is it unused, and do you still have the original packaging, accessories and manuals?

## Grounding

- Live model: `gpt-6.1-terra`.
- Tools used: `search_store_policies`.
- Key behavior verified: The answer describes the seven-calendar-day receipt-based rule and conditions, with store-paid return freight and clarification before individual approval.
