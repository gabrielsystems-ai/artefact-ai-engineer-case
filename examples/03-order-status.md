# Customer-bound order status

## Purpose

Demonstrate an application-scoped order lookup with recorded tracking and an estimate rather than confirmed receipt.

## Conversation

**Customer**

Qual é o status do meu pedido 8? Ele já tem código de rastreio? Qual o total registrado e a previsão de entrega?

**Assistant**

O pedido **8 foi enviado**. Os dados registrados são:

- **Código de rastreio:** BRJL5544332BR
- **Total:** R$ 349,90
- **Previsão de entrega:** 28/02/2026

A data é uma previsão e não confirma que o pedido foi entregue.

## Grounding

- Live model: `gpt-6.1-terra`.
- Tools used: `get_order_status`.
- Key behavior verified: The owned order retains its recorded status, historical total, tracking and estimated delivery; customer identity is not exposed.
