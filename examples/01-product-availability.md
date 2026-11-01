# Product price and availability

## Purpose

Demonstrate operational product lookup without applying an inactive promotion.

## Conversation

**Customer**

How much is the Takamine GD20 and is it currently available?

**Assistant**

The **Takamine GD20 Dreadnought Natural** is **R$2,199.00** and is currently available. We have 5 in stock.

## Grounding

- Live model: `gpt-6.1-terra`.
- Tools used: `search_products`.
- Key behavior verified: The current price is BRL 2,199.00; the product is available with five units, and the inactive promotion is not applied.
