# Pedido atrasado e reclamação

> Status em tempo real, detecção de atraso e abertura de chamado (escrita controlada pela constituição).
>
> Modelo: `nvidia/nemotron-3.5-super-vl:free` · relógio simulado: 25/03/2026 14:30 · gerado com `python -m emporio.evals --write-conversations` (conversa real com o modelo, não editada).

**Cliente:** Oi, cadê meu pedido 8? Ainda não chegou.

**Lia:** Oi! Para consultar o pedido 8, preciso confirmar sua identidade primeiro (é uma regra de privacidade da loja).

Você poderia me informar o **e-mail** ou o **telefone** cadastrado no pedido? Assim eu consigo verificar e te dizer o status da entrega.

<details><summary>Bastidores</summary>

- 🛡️ constituição: aprovada

</details>

**Cliente:** Meu telefone é (67) 99654-7821

**Lia:** Oi, Ana! Consegui acessar seu pedido. Aqui está o que encontrei:

- **Pedido 8:** Kala KA-C Concert Mogno (ukulele)
- **Status:** enviado (em transporte)
- **Previsão de entrega:** 28/02/2026 — já está atrasado
- **Código de rastreio:** BRJL5544332BR

Você pode acompanhar a entrega pelo site dos Correios com esse código.

Como o pedido está atrasado, posso abrir um chamado de reclamação para a equipe da loja verificar o que está acontecendo com a entrega. A equipe retorna em até 24 horas úteis. Você quer que eu abra esse chamado para você?

<details><summary>Bastidores</summary>

- 🔧 `verify_customer(order_id=8, phone="(67) 99654-7821")` → regra `ID_MATCH_anon`
- ↪ respondido pelo modelo reserva `nvidia/nemotron-3-ultra-550b-a55b:free`
- 🔧 `get_orders(order_id=8)`
- 🛡️ constituição: aprovada

</details>

**Cliente:** Quero registrar uma reclamação, por favor.

**Lia:** Pronto, Ana! Registrei sua reclamação com o protocolo **EM-20260325-60DA**.

A equipe da Empório da Música vai verificar o andamento da entrega do seu ukulele e retorna para você em até 24 horas úteis, pelo telefone (67) 99654-7821.

Precisa de mais alguma coisa?

<details><summary>Bastidores</summary>

- 🔧 `open_ticket(kind="reclamacao", summary="Cliente Ana reclama de atraso na entrega do pedido 8 (ukulele Kala KA-C Concert Mogno). Previsão era 28/02/2026 e ainda não chegou. Código de rastreio: BRJL5544332BR.", contact="(67) 99654-7821")`
- 🛡️ constituição: aprovada

</details>
