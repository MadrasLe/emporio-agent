# Pedido atrasado e reclamação

> Status em tempo real, detecção de atraso e abertura de chamado (escrita controlada pela constituição).
>
> Modelo: `nvidia/nemotron-3.5-super-vl:free` · relógio simulado: 25/03/2026 14:30 · gerado com `python -m emporio.evals --write-conversations` (conversa real com o modelo, não editada).

**Cliente:** Oi, cadê meu pedido 8? Ainda não chegou.

**Lia:** Oi! Para consultar o pedido 8, preciso confirmar sua identidade primeiro (é uma regra de privacidade da loja).

Você poderia me informar o **e-mail** ou o **telefone** cadastrado no pedido? Com isso eu consigo verificar e te dizer o status da entrega.

<details><summary>Bastidores</summary>

- 🛡️ constituição: aprovada

</details>

**Cliente:** Meu telefone é (67) 99654-7821

**Lia:** Oi, Ana! Verifiquei seu pedido 8 aqui. 🎵

O status é **enviado (em transporte)**, mas a previsão de entrega era 28/02 e já estamos em 25/03 — então o pedido está atrasado mesmo. Peço desculpas por isso.

O código de rastreio é **BRJL5544332BR**. Você pode acompanhar no site dos Correios ou da Jadlog.

Como o pedido está atrasado, posso abrir um chamado de reclamação para a equipe investigar. A resposta vem em até 24 horas úteis. Você quer que eu registre?

<details><summary>Bastidores</summary>

- 🔧 `verify_customer(order_id=8, phone="(67) 99654-7821")` → regra `ID_MATCH_anon`
- 🔧 `get_orders(order_id=8)`
- 🛡️ constituição: aprovada

</details>

**Cliente:** Quero registrar uma reclamação, por favor.

**Lia:** Registrado! O protocolo da sua reclamação é **EM-20260325-A849**. A equipe da Empório da Música vai investigar o atraso do seu pedido e retorna em até 24 horas úteis.

Qualquer coisa, é só chamar. Até mais! 🎵

<details><summary>Bastidores</summary>

- 🔧 `open_ticket(kind="reclamacao", summary="Pedido 8 (Kala KA-C Concert Mogno) enviado em 15/02 com previsão de entrega 28/02, mas ainda não chegou. Código de rastreio BRJL5544332BR. Cliente Ana, telefone (67) 99654-7821.")`
- 🛡️ constituição: aprovada

</details>
