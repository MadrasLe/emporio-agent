# Preço, PIX e parcelamento

> Preço vem da ferramenta; desconto do PIX e parcela mínima são calculados pelas regras, não pelo LLM.
>
> Modelo: `nvidia/nemotron-3.5-super-vl:free` · relógio simulado: 25/03/2026 14:30 · gerado com `python -m emporio.evals --write-conversations` (conversa real com o modelo, não editada).

**Cliente:** Quanto custa o Takamine GD20?

**Lia:** O Takamine GD20 Dreadnought Natural está disponível por **R$ 2.199,00**.

Condições:
- **À vista no PIX:** R$ 2.089,05 (5% de desconto)
- **Parcelado:** até 12x de R$ 183,25 sem juros

Temos 5 unidades em estoque. Quer saber mais alguma coisa sobre ele?

<details><summary>Bastidores</summary>

- 🔧 `get_product(product="Takamine GD20")`
- 🛡️ constituição: aprovada

</details>

**Cliente:** E o ukulele Ohana CK-20? Dá pra fazer em 6x?

**Lia:** O ukulele Ohana CK-20 Concert Natural está em promoção:

- **Preço promocional:** R$ 439,20 (20% off, de R$ 549,00)
- **À vista no PIX:** R$ 439,20 (sem desconto extra, pois promoções não são cumulativas)
- **Parcelamento máximo:** 5x de R$ 87,84 sem juros

Infelizmente **não dá para fazer em 6x**, porque o valor da parcela ficaria abaixo do mínimo permitido para essa faixa (R$ 80,00). O máximo são 5x.

Temos 6 unidades em estoque. Quer mais alguma informação?

<details><summary>Bastidores</summary>

- 🔧 `get_product(product="Ohana CK-20", installments=6)`
- 🛡️ constituição: aprovada

</details>
