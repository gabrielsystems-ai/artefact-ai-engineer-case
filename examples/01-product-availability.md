# Product price and availability

## Purpose

Demonstrate operational product lookup without applying an inactive promotion.

## Conversation

**Customer**

Quanto custa o Takamine GD20 e ele está disponível?

**Assistant**

O **Takamine GD20 Dreadnought Natural** custa **R$ 2.199,00** e está disponível. Temos 5 unidades em estoque.

## Grounding

- Live model: `gpt-6.1-terra`.
- Tools used: `search_products`.
- Key behavior verified: The current price is BRL 2,199.00; the product is available with five units, and the inactive promotion is not applied.
