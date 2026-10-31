# Devolução por arrependimento (política + dados do pedido)

> Exige verificação de identidade (LGPD) e aplica as regras de troca/devolução/garantia ao pedido.
>
> Modelo: `nvidia/nemotron-3.5-super-vl:free` · relógio simulado: 25/03/2026 14:30 · gerado com `python -m emporio.evals --write-conversations` (conversa real com o modelo, não editada).

**Cliente:** Me arrependi da minha compra, posso devolver meu pedido?

**Lia:** Oi! Pode ser, sim. Para verificar as regras de devolução do seu pedido, preciso confirmar sua identidade primeiro (é uma exigência de privacidade da loja).

Me passa, por favor:
1. O número do seu pedido
2. O e-mail ou telefone cadastrado na compra

Com esses dados eu consigo checar tudo pra você. 🎸

<details><summary>Bastidores</summary>

- 🛡️ constituição: aprovada

</details>

**Cliente:** É o pedido 7, meu e-mail é leticia.rocha@jmail.com

**Lia:** Oi, Letícia! Verifiquei seu pedido 7 e aqui está o que encontrei:

**Arrependimento:** infelizmente não é possível. O prazo de 7 dias para desistir da compra após o recebimento já terminou (era até 24/02/2026).

**Troca por preferência (cor, modelo, etc.):** também não está disponível, pois o mesmo prazo de 7 dias expirou.

**Defeito de fabricação:** se o instrumento apresentar algum problema de fabricação, ainda é possível acionar a garantia legal. O prazo vai até **18/05/2026** e a Empório pode intermediar o processo com o fabricante. Atenção: desgaste natural, mau uso, quedas e reparos por terceiros não são cobertos.

Se você quiser seguir com alguma dessas opções (especialmente se houver defeito), posso abrir um chamado para a equipe analisar seu caso. Eles retornam em até 24 horas úteis.

Quer que eu abra o chamado para você?

<details><summary>Bastidores</summary>

- 🔧 `verify_customer(order_id=7, email="leticia.rocha@jmail.com")` → regra `ID_MATCH_anon`
- 🔧 `check_return(order_id=7, reason="arrependimento")` → regra `RET_REGRET_EXPIRED / RET_DEFECT_LEGAL / RET_PREF_EXPIRED`
- 🛡️ constituição: aprovada

</details>
