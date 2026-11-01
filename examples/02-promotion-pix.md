# Promotion, PIX and conversation continuity

## Purpose

Demonstrate non-stacking discounts and a related follow-up in the same session.

## Conversation

**Customer**

Qual é o preço do produto 127 no PIX?

**Assistant**

O **Kalani KAL-700T Tenor Natural (produto 127)** custa **R$ 323,10 no PIX**. O preço já inclui a promoção de 10%; não há desconto adicional para PIX.

**Customer**

E o preço antes da promoção?

**Assistant**

Antes da promoção, o preço era **R$ 359,00**.

## Grounding

- Live model: `gpt-6.1-terra`.
- Tools used: `get_product_details`.
- Key behavior verified: The active 10% promotion gives BRL 323.10 even for PIX; the list price remains BRL 359.00.
