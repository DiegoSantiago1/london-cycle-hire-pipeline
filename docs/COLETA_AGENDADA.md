# Coleta a cada 15 minutos com um agendador externo

O cron do GitHub Actions é "melhor esforço". Neste repositório ele passou a rodar a coleta a cada 3 a 8 horas, em vez de a cada 15 minutos. Em 04/10/2026, por exemplo, rodaram 5 das 96 janelas. Todas as execuções deram certo: o problema é só o horário. O próprio painel de saúde mediu isso, e o job diário falha de propósito quando os dados ficam velhos (D40).

A solução gratuita, sem cartão e sem mudar a arquitetura: um agendador externo chama o workflow `coleta` pela API do GitHub nos mesmos minutos (7, 22, 37 e 52). O cron do GitHub continua como reserva. A AWS (Lambda + EventBridge) segue como a fase 7, quando houver conta.

## Como fica registrado

A chamada externa dispara o workflow com `gatilho=agendador_externo`. O registro da execução grava `evento = "agendador_externo"`, e a saúde da coleta conta essa execução como agendada, junto com o cron do GitHub. Um disparo manual (botão "Run workflow") continua sendo `workflow_dispatch` e fica fora da medição de atraso.

Duas execuções na mesma janela (cron do GitHub e agendador externo) não distorcem nada: cada retrato vale até o seguinte, e a saúde mede a primeira execução de cada janela.

## Passo a passo (uma vez, cerca de 10 minutos)

### 1. Token só para disparar este workflow

1. No GitHub: **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Nome: `coleta-agendador`. Validade: a maior que a tela permitir (anote a data para renovar).
3. **Repository access:** *Only select repositories* → `london-cycle-hire-pipeline`.
4. **Permissions → Repository permissions → Actions: Read and write.** Nenhuma outra.
5. Gere e copie o token. Ele não aparece de novo. Não cole em chat, código ou commit.

Com essa permissão, o token só consegue disparar e ver workflows deste repositório. Não lê nem altera código.

### 2. Tarefa no cron-job.org

1. Crie a conta gratuita em https://cron-job.org.
2. **Create cronjob**:
   - **URL:** `https://api.github.com/repos/DiegoSantiago1/london-cycle-hire-pipeline/actions/workflows/coleta.yml/dispatches`
   - **Schedule:** personalizado, minutos `7,22,37,52`, todas as horas, todos os dias.
3. Em **Advanced**:
   - **Request method:** `POST`
   - **Headers:**
     - `Accept: application/vnd.github+json`
     - `Authorization: Bearer <o token do passo 1>`
     - `Content-Type: application/json`
   - **Request body:** `{"ref":"main","inputs":{"gatilho":"agendador_externo"}}`
4. Salve e use **Test run**. A resposta certa é **HTTP 204** (sem corpo).

### 3. Conferir

Em Actions → coleta deve aparecer uma execução nova, disparada por `workflow_dispatch`. No registro da execução (release do dia, arquivo `execucao_...json`), o campo `evento` vem como `agendador_externo`. No dia seguinte, o painel de saúde da página mostra perto de 96 janelas coletadas.

## Se algo der errado

- **401 ou 403:** token errado, vencido ou sem a permissão Actions.
- **404:** URL errada ou token sem acesso a este repositório.
- **422:** o corpo não tem `"ref":"main"` ou o `gatilho` não é um dos valores aceitos (`manual`, `agendador_externo`).
- **Token vencido:** gere outro com o mesmo passo 1 e troque só o cabeçalho `Authorization` no cron-job.org.
