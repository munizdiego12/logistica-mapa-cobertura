# Backup do banco (Neon)

O workflow `.github/workflows/backup.yml` ("Backup do Neon") tira uma cópia do banco todo **domingo às 06:00 UTC** (03:00 em Brasília) e quando você manda rodar. A cópia é criptografada e fica guardada como *artifact* do GitHub por **30 dias**, com o nome `backup-neon-AAAAMMDD.dump.gpg`.

> **Atenção: o repositório é público.** Os artifacts de repositório público podem ser baixados por qualquer pessoa logada no GitHub. O arquivo só é seguro porque está criptografado: **a senha do backup (`BACKUP_PASSPHRASE`) é a única proteção**. Use 32 caracteres ou mais, aleatórios, e nunca a reutilize em outro lugar. O backup contém dados pessoais (e-mails e senhas com hash dos operadores).

## Como ativar (uma vez)

1. No Neon, copie a string de conexão **direta** (sem `-pooler` no endereço).
2. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**:
   - `DATABASE_URL`: a string direta do Neon.
   - `BACKUP_PASSPHRASE`: senha longa e aleatória (32+ caracteres). Guarde-a também em um gerenciador de senhas: **sem ela o backup não abre e não há como recuperá-la**.
3. Aba **Actions → Backup do Neon → Run workflow** para a primeira execução, e confira que o artifact apareceu no fim da página da execução.
4. Teste a restauração (abaixo) pelo menos uma vez.

## Como abrir (descriptografar) o backup

Baixe o arquivo `.dump.gpg` da página da execução (aba Actions). É preciso ter o GPG instalado (no Windows, o Gpg4win; o Git for Windows já traz o `gpg`). Se o GitHub entregar o arquivo dentro de um `.zip`, descompacte antes.

```
gpg --output backup-neon-AAAAMMDD.dump --decrypt backup-neon-AAAAMMDD.dump.gpg
```

O `gpg` pede a senha (`BACKUP_PASSPHRASE`). No PowerShell **não use `>`** para gravar o resultado (corrompe arquivo binário): use sempre `--output`. Depois de usar, apague o `.dump` em claro.

## Como restaurar em um banco novo

Use o `pg_restore` **versão 18** (a mesma do servidor Neon). Crie um banco novo e **vazio** (no Neon, ou em outro PostgreSQL 18) e guarde a string de conexão dele **só na variável de ambiente**, nunca em arquivo, em comando visível ou em conversa:

```
# PowerShell
$env:BANCO_NOVO = "<string de conexão do banco novo>"
pg_restore --no-owner --no-privileges --dbname $env:BANCO_NOVO backup-neon-AAAAMMDD.dump
Remove-Item Env:BANCO_NOVO
```

```
# Bash
export BANCO_NOVO='<string de conexão do banco novo>'
pg_restore --no-owner --no-privileges --dbname "$BANCO_NOVO" backup-neon-AAAAMMDD.dump
unset BANCO_NOVO
```

Se a string aparecer como argumento do comando, quem olhar a lista de processos a vê; por isso, se preferir, use as variáveis do libpq (`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE`) e rode `pg_restore --no-owner --no-privileges --dbname "$PGDATABASE" ...`. Avisos de extensão ou de papel (*role*) que já existe podem aparecer e em geral são inofensivos; erros de tabela ou de dados não são.

Depois de restaurar, aponte o backend (`DATABASE_URL` no Render) para o banco novo e confira o login e uma consulta de CEP.

## Como testar a restauração (sem risco) em uma branch do Neon

1. No Neon, abra o projeto → **Branches → Create branch** (a partir do principal). A branch é uma cópia separada: mexer nela não afeta a produção.
2. Na branch, crie um banco novo e vazio (**Databases → New database**, por exemplo `teste_restore`) e copie a string de conexão **direta** dele.
3. Descriptografe o backup e rode o `pg_restore` como acima, usando a string dessa branch.
4. Confira os números, no SQL Editor da branch:
   ```sql
   SELECT count(*) FROM operadores;
   SELECT count(*) FROM cep_prefixos;   -- por volta de 24.600
   SELECT count(*) FROM ibge_municipios; -- 5.571
   ```
5. Apague a branch quando terminar e o `.dump` em claro do seu computador.

Repita esse teste de vez em quando (por exemplo a cada trimestre): backup que nunca foi restaurado não é garantia.

## Aviso: o GitHub desativa agendamentos parados

O GitHub **desativa os workflows agendados após 60 dias sem atividade no repositório** (commits, por exemplo). Quando isso acontece, o backup semanal para em silêncio. Para evitar:

- Olhe a aba **Actions** de tempos em tempos e confira se há um artifact recente.
- Se o workflow aparecer desativado, clique em **Enable workflow**; fazer um commit no repositório também reinicia a contagem.
- Para forçar uma cópia a qualquer momento: **Run workflow**.

## Como trocar a senha do backup

A troca vale só para os backups **novos**; os antigos continuam precisando da senha antiga.

1. Gere uma senha nova (32+ caracteres aleatórios). Por exemplo, no PowerShell: `-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 40 | ForEach-Object {[char]$_})`.
2. No GitHub: **Settings → Secrets and variables → Actions → BACKUP_PASSPHRASE → Update** e cole a nova senha.
3. Rode o workflow à mão e confira que o novo artifact abre com a nova senha.
4. **Guarde a senha antiga** enquanto existirem backups feitos com ela (30 dias). Se a senha antiga vazou, baixe e apague esses artifacts (aba Actions → a execução → apagar o artifact) depois que o novo backup estiver confirmado.

Se a senha do **banco** mudar no Neon, atualize também o secret `DATABASE_URL`.

## O que o workflow confere antes de guardar

- O `pg_dump` é da versão 18 (a do servidor) e usa a string só por variável de ambiente; a senha não aparece em log nem em linha de comando.
- O dump tem pelo menos 100 KB e o `pg_restore --list` mostra as tabelas `operadores` e `cep_prefixos`; senão, o workflow falha e você é avisado pelo GitHub.
- O arquivo criptografado é aberto de novo e comparado com o original **antes** de o dump em claro ser apagado; só o `.gpg` vai para o artifact.
