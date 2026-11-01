# Customer-bound order status

## Purpose

Demonstrate an application-scoped order lookup with recorded tracking and an estimate rather than confirmed receipt.

## Conversation

**Customer**

What is the status of my order 8? Does it have tracking information yet? What is the recorded total and estimated delivery date?

**Assistant**

Your order **#8 has shipped**.

- **Tracking code:** BRJL5544332BR
- **Recorded total:** R$ 349.90
- **Estimated delivery:** February 28, 2026

The delivery date is an estimate, not confirmation that the order was received.

## Grounding

- Live model: `gpt-6.1-terra`.
- Tools used: `get_order_status`.
- Key behavior verified: The owned order retains its recorded status, historical total, tracking and estimated delivery; customer identity is not exposed.
