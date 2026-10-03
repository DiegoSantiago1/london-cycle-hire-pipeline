-- =====================================================================
-- Bootstrap: cria o usuário (role) e os bancos deste projeto dentro do
-- container PostgreSQL compartilhado com outros projetos.
--   :usuario, :senha   dono dos bancos (migrations, carga e dbt)
--   :banco             banco principal (dados do projeto)
--   :banco_teste       banco dos testes (apagado e recriado pelo pytest)
--
-- Roda como superusuário, uma vez (e pode rodar de novo sem quebrar nada).
-- Não use diretamente: o `python -m bicicletas.bootstrap` lê o .env, valida
-- os valores e envia este arquivo ao psql com as variáveis já definidas.
--
-- Por que não é uma migração do Alembic: criar role e banco são operações
-- do servidor inteiro (exigem superusuário) e CREATE DATABASE não roda
-- dentro de transação. As migrações rodam depois, já como o usuário do
-- projeto, dentro do banco dele.
--
-- Cada comando é montado com format(): %I cita identificadores e %L cita
-- literais (a senha), o que impede SQL injection pelas variáveis. O \gexec
-- executa cada linha resultante como um comando; o WHERE NOT EXISTS torna
-- tudo idempotente.
-- =====================================================================
\set ON_ERROR_STOP on

-- 0. Trava (container compartilhado): se um usuário com o nome do .env já existe e é
--    superusuário, ou é dono de bancos que não são deste projeto, para tudo antes de
--    alterar qualquer coisa. Sem isso, um nome repetido trocaria a senha e os
--    privilégios de um usuário de outro projeto.
SELECT format('DO $trava$ BEGIN RAISE EXCEPTION %L; END $trava$',
              'O usuário ' || r.rolname || ' já existe e é superusuário ou dono de outros '
              || 'bancos (' || coalesce(string_agg(d.datname, ', '), '') || '): '
              || 'escolha outro nome no .env.')
FROM pg_roles r
LEFT JOIN pg_database d
       ON d.datdba = r.oid AND d.datname NOT IN (:'banco', :'banco_teste')
WHERE r.rolname = :'usuario'
GROUP BY r.rolname, r.rolsuper
HAVING r.rolsuper OR count(d.datname) > 0
\gexec

-- 1. Usuário do projeto: pode logar, mas não é superusuário, não cria
--    bancos, não cria roles e não ignora regras de segurança de linha.
SELECT format('CREATE ROLE %I LOGIN', :'usuario')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'usuario')
\gexec

-- Sempre reaplica atributos e senha: se o role já existia, fica em
-- sincronia com o .env e sem privilégios extras.
SELECT format(
    'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'usuario', :'senha'
)
\gexec

-- 2. Bancos do projeto (principal e de testes), pertencentes ao usuário do projeto.
SELECT format('CREATE DATABASE %I OWNER %I ENCODING %L TEMPLATE template0', b.nome, :'usuario', 'UTF8')
FROM unnest(ARRAY[:'banco', :'banco_teste']) AS b(nome)
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = b.nome)
\gexec

SELECT format('ALTER DATABASE %I OWNER TO %I', b.nome, :'usuario')
FROM unnest(ARRAY[:'banco', :'banco_teste']) AS b(nome)
\gexec

-- 3. Fuso horário da sessão: as perguntas de negócio são no horário de Londres ("vazia
--    às 8h" é 8h em Londres, com horário de verão). As colunas são TIMESTAMPTZ, então o
--    instante gravado não muda; o fuso só define como datas e horas são lidas e
--    exibidas. Mesmo assim, as transformações que dependem de hora local fixam o fuso
--    explicitamente (lição do Projeto 3: não depender do fuso de quem roda).
SELECT format('ALTER DATABASE %I SET timezone TO %L', b.nome, 'Europe/London')
FROM unnest(ARRAY[:'banco', :'banco_teste']) AS b(nome)
\gexec

-- 4. Por padrão o PostgreSQL deixa QUALQUER role conectar em qualquer banco
--    (privilégio CONNECT do PUBLIC). Aqui só o dono conecta.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', b.nome)
FROM unnest(ARRAY[:'banco', :'banco_teste']) AS b(nome)
\gexec
