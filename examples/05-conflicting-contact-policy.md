# Conflicting contact information in English

## Purpose

Demonstrate bilingual policy retrieval and explicit uncertainty when supplied contact sources disagree.

## Conversation

**Customer**

What is the store's WhatsApp number?

**Assistant**

The store’s guidance lists two different WhatsApp numbers:

- Company details: **(67) 3341-4444**
- WhatsApp service section: **(67) 3321-4500**

Please confirm with the store which number is current.

## Grounding

- Live model: `gpt-6.1-terra`.
- Tools used: `search_store_policies`.
- Key behavior verified: Both conflicting store contact numbers are surfaced rather than silently selecting one as authoritative.
