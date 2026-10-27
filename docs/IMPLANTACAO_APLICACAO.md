# Implantação da aplicação — Docker Hub + AWS Academy

## Estado desta entrega

Implementação local de infraestrutura, publicação e deploy. Os comandos abaixo criam
recursos e publicam imagens quando executados com seus parâmetros. Não houve criação,
atualização ou exclusão de recursos AWS durante a implementação.

Componentes:

| Arquivo | Responsabilidade |
|---|---|
| `files/application.yaml` | EC2s frontend/backend/MySQL, grupos próprios, EIP, EBS de dados e bucket de backup |
| `scripts/application.py` | Change sets, acompanhamento AWS, preparação do pedido n8n e deploy via CLI |
| `scripts/remote_application.py` | Bootstrap MySQL, backup, deploy de containers, smoke tests e rollback |
| `scripts/publish_images.py` | Build/testes e publicação das imagens no Docker Hub |
| `application-n8n-noctua.json` | Provisiona/atualiza `application.yaml`, aguarda CloudFormation/SSM e implanta os três componentes |
| `files/application.example.json` | Contrato de configuração, sem credenciais |

O workflow original `infra-n8n-noctua.json` permanece independente. No template
`compute.yaml`, a definição antiga `EC2Database` foi removida. Isso não exclui uma
instância já criada: a seção 10 realiza essa atualização explicitamente depois da
validação da aplicação. O workflow original exportado tem o gatilho conectado à
leitura de `network.yaml` para criar a infraestrutura-base; use o **novo workflow**
para provisionar a stack de aplicação e implantar seus serviços na mesma execução.

## 1. Arquitetura e pré-requisitos

```text
Navegador -> EC2 frontend / Nginx (subnet pública, EIP)
                   -> /api/ -> EC2 backend:8080 (PRIVATE-BACKEND)
                                  -> MySQL:3306 (PRIVATE-DB)
                                  -> Athena / Glue / S3 pela role
```

- Python 3.10+, Docker com containers Linux e AWS CLI v2 no computador.
- Node.js para executar os testes locais do código do workflow.
- Os três projetos em pastas irmãs. Caminhos alternativos são aceitos em `--backend`,
  `--frontend` (publicação) e `--schema` (deploy/preparação).
- Rede-base criada com exports `VPC-ID`, `PUBLIC-SUBNET`, `PRIVATE-BACKEND` e `PRIVATE-DB`.
- Região `us-east-1`: a rede existente fixa suas subnets em `us-east-1a`.
- NAT/saída funcionando nas subnets privadas.
- `LabInstanceProfile` disponível e permitido. Não há criação de roles IAM nesta entrega.
- Instâncias padrão `t3.small`; altere para tipos permitidos pelo laboratório.

A identidade de implantação precisa de CloudFormation (incluindo change sets), EC2,
S3 e associação do instance profile. Para preparar/executar releases, também precisa
de `ssm:DescribeInstanceInformation`, `ssm:SendCommand` e `ssm:GetCommandInvocation`.
O workflow n8n também usa `ssm:DescribeParameters` para conferir os metadados dos segredos.
Criar a senha requer `ssm:PutParameter`. O CloudFormation precisa poder resolver a AMI
Ubuntu no parâmetro público SSM.

A role das EC2s precisa das permissões do SSM Agent e de `ssm:GetParameter` para os
segredos usados, além de KMS quando aplicável. A EC2 banco precisa de `s3:PutObject`
no bucket de backup. O backend precisa de acesso a Athena, Glue e aos dados/resultados
S3. No Academy, confirme essas permissões com o laboratório; o nome da role sozinho
não garante o acesso.

## 2. Credenciais temporárias do laboratório

Inicie o laboratório. Pelo editor, configure um perfil em
`C:\Users\SEU_USUARIO\.aws\credentials` com os **três valores da mesma sessão**:

```ini
[noctua-lab]
aws_access_key_id = VALOR_DA_SESSAO
aws_secret_access_key = VALOR_DA_SESSAO
aws_session_token = VALOR_DA_SESSAO
```

Valide em PowerShell:

```powershell
aws sts get-caller-identity --profile noctua-lab --region us-east-1
```

Quando expirar, substitua os três valores juntos. O portal Academy não fornece ao
script um mecanismo de renovação indefinida dessas credenciais copiadas. Não coloque
os valores no Git, em `application.local.json`, em UserData ou em imagens.

Nas EC2s, AWS CLI e SDK usam a role pelo IMDSv2 e renovam suas credenciais sem copiar
as chaves do computador. O template configura hop limit 2 para Docker bridge. Uma
sessão de laboratório encerrada pode parar instâncias/revogar acessos; a role não
mantém o laboratório ligado.

No n8n, crie **uma credencial AWS** na região `us-east-1`, habilite credenciais
temporárias/session token e preencha o mesmo conjunto. Se a versão instalada não
oferecer session token, use o deploy CLI até atualizar/configurar um método compatível.
Associe essa credencial aos quatro nós HTTP AWS do novo workflow: **CloudFormation API**,
**SSM infrastructure API**, **Send SSM command** e **Get SSM status**. Sua atualização
centralizada vale para todos; ela não é atualizada automaticamente pelo perfil CLI.

## 3. Preencher a configuração

Pelo editor, copie `files/application.example.json` para `files/application.local.json`.
O arquivo local é ignorado pelo Git. Preencha:

- `profile`: perfil configurado acima; vazio para usar a cadeia padrão da AWS CLI.
- `frontend_ingress_cidr`: seu IP público `/32` para a validação inicial por HTTP.
- `instance_profile` e os tipos de instância permitidos.
- `backend_image` e `frontend_image`: digests publicados na próxima seção.
- `compute_stack_name`: stack existente com outputs `GlueDatabaseName` e `AthenaWorkGroupName`.
- `athena_enabled`: `true` para exigir também a validação real de Athena. Se usar
  `false` para validar primeiro o MySQL, a saída informa Athena não validado e os
  endpoints de funcionários continuam retornando erro.

`backend_memory` limita o container (padrão `768m`); a JVM usa até 65% desse limite
para heap. Dimensione após observar o consumo. Todos os containers usam rotação de logs.

## 4. Construir e publicar no Docker Hub

Crie no Docker Hub:

- `SEU_USUARIO/noctua-backend`
- `SEU_USUARIO/noctua-frontend`

No PowerShell, na raiz de **noctua-infraestructure**, autentique-se. Use um token de
publicação no prompt de senha, não o token como argumento do comando:

```powershell
docker login --username SEU_USUARIO
python scripts/publish_images.py --namespace SEU_USUARIO --release release-001
```

O script constrói ambas as imagens para `linux/amd64`, executa os testes do Dockerfile
do backend e o verificador de empacotamento, publica as imagens e imprime referências
`docker.io/usuario/imagem@sha256:...`. Copie as referências para a configuração local.
Não reutilize a tag de uma release; o deploy exige digest, não `latest`.

Imagens públicas podem ser baixadas anonimamente, sujeitas aos limites do Docker Hub.
Para imagens privadas (ou pull autenticado), crie pelo console SSM um `SecureString`
com o JSON abaixo e informe seu nome em `dockerhub_credentials_parameter`:

```json
{"username":"SEU_USUARIO","token":"TOKEN_DOCKER_HUB_SOMENTE_LEITURA"}
```

O token de leitura é buscado pela EC2 e usado com `docker login --password-stdin` em
um diretório temporário removido depois do pull. O token Docker Hub não depende da
sessão AWS, mas tem sua própria validade/rotação. Não reutilize o token de publicação
como credencial de leitura quando puder usar escopos separados.

## 5. Criar a senha do banco

```powershell
python scripts/application.py init-db-secret
```

Cria uma senha aleatória de 64 caracteres em `db_password_parameter`, como
`SecureString`, sem imprimir o valor. Não sobrescreve senha existente. Se já existe,
prossiga usando o mesmo parâmetro. Senhas fornecidas manualmente devem ter 32–128
caracteres usando letras, números, `.`, `_`, `~` ou `-`.

## 6. Provisionar as três instâncias

Esta seção descreve o provisionamento via CLI. Para provisionar e implantar pelo n8n,
vá à seção 8 depois de configurar/publicar as imagens e criar os segredos.

```powershell
python scripts/application.py plan
```

O comando valida o template, verifica os exports da rede, cria um change set e mostra
as inclusões/alterações/substituições. Copie o ARN retornado e revise no CloudFormation.
Para a primeira criação, espere três EC2s, seus SGs, launch template, EIP, EBS e bucket.

```powershell
python scripts/application.py apply --change-set ARN_DO_CHANGE_SET
```

O script acompanha a conclusão, inclusive estados de falha. Em novas execuções,
`plan` usa atualização, preserva parâmetros não gerenciados pelo JSON e reconhece
o caso sem mudanças. Em um plano sem mudanças, não há novo `apply` a executar.

Use `plan/apply` para infraestrutura e `deploy` para releases. Atualizar imagens não
modifica a stack. Trocar a AMI/launch template pode substituir EC2s; revise o plano.

O bootstrap instala Docker, AWS CLI, clientes e SSM Agent. O deploy aguarda a instância
Online no SSM e o arquivo `/opt/noctua/bootstrap-ready`. `CREATE_COMPLETE` não é
tratado como prova de que a aplicação já está saudável.

## 7. Primeiro deploy via CLI

```powershell
python scripts/application.py deploy
```

Ordem efetivamente executada:

1. Consultar os outputs atuais de aplicação e Athena.
2. Aguardar as três EC2s no SSM.
3. Enviar pacote de scripts/schema por SSM, com checksum e diretório temporário.
4. Preparar o banco, seu usuário e executar backup inicial.
5. Implantar e validar o backend.
6. Implantar e validar frontend e proxy.

O pacote enviado não contém credenciais AWS nem valores dos segredos. A mesma role
disponível no laboratório é usada pelas EC2s; isso não implementa roles mínimas por
serviço quando o Academy só permite `LabInstanceProfile`.

### Banco

O EBS separado é montado em `/srv/noctua-mysql`; seu subdiretório de dados é montado
em `/var/lib/mysql`. O serviço depende das montagens no boot. O baseline oficial cria
11 tabelas. Um checksum em `noctua_deployment.schema_versions` registra a conclusão.

Reexecutar preserva os dados e não reaplica o DDL. Se houver schema parcial ou checksum
diferente, o processo falha e requer diagnóstico/migração explícita. Esta entrega
implementa o baseline controlado; não inventa migrações para alterações futuras.

O usuário `noctua_api` recebe apenas SELECT, é restrito ao IP privado atual do backend
e exige TLS. A URL JDBC usa `sslMode=REQUIRED`: transporte criptografado, sem validação
de identidade por CA/nome. A validação de identidade é uma evolução separada.

O arquivo `/etc/mysql/mysql.conf.d/noctua.cnf` não contém segredos e usa permissão
`0644` para que o usuário do serviço MySQL possa lê-lo. O bootstrap verifica os
valores em execução de `bind_address` e `require_secure_transport`, reiniciando o
serviço somente se eles ainda não refletirem a configuração. Isso também corrige
ambientes anteriores em que o arquivo foi criado com permissão `0600`.

### Containers e validação

O deploy gera arquivos restritos em `/opt/noctua`, baixa a imagem exata e recria o
container com `--restart unless-stopped`. Há breve indisponibilidade ao substituir um
container: não é uma implementação blue/green.

Backend: health JDBC + quatro rotas JDBC + quatro rotas Athena, quando habilitadas.
Frontend: HTML, rotas da API pelo proxy e validação TLS quando configurado.

Com Athena habilitado, criar a stack e enviar o CSV ao bronze não basta: o job
Silver precisa concluir e o crawler precisa catalogar a tabela consultada pelos
SQLs da imagem. Confirme o nome real da tabela nesses SQLs e no Glue Catalog. Um
health JDBC `UP` com erro `TABLE_NOT_FOUND` nas rotas de funcionários indica que
o processamento/catalogação de dados ainda está pendente; não é falha de conexão
com o MySQL. Execute o processamento e o crawler antes de repetir o deploy.

Nesta configuração, os indicadores usam a camada Silver. `silver.py` grava o
dataset principal em Parquet diretamente em `s3://noctua-2026-bucket-silver/silver/`, alvo
do crawler `noctua-silver-crawler`, para gerar `noctua_analytics.silver`. A saída
auxiliar fica em `silver_gerais/`, fora do alvo, com `cargo_map` serializado como
JSON em uma coluna de texto compatível com CSV. Não misture esquemas diferentes
em subpastas de `silver/`.

Parquet evita deslocamento de colunas por vírgulas/aspas nas respostas textuais e
preserva os indicadores de linguagem como inteiros, incluindo valores nulos.
O CSV de origem é lido como documento completo por `csv.reader`, nos workers
Spark, preservando respostas multilinha e aspas duplicadas. A leitura JVM do
Spark, inclusive com `multiLine=true`, apresentou divergências nessa fonte. Os
arquivos são distribuídos por `binaryFiles`; cada arquivo precisa caber na memória
do worker. O CSV atual tem aproximadamente 10 MB. Cabeçalhos diferentes são
rejeitados, campos extras são preservados e campos ausentes permanecem nulos.
O job rejeita indicadores fora do domínio 0/1. O script Gold aceita os arquivos
`.parquet` recebidos por evento; para ler manualmente o prefixo inteiro, informe
`--input_format parquet` ao job Gold.

Na migração de uma tabela antiga particionada por subpastas, confira no Glue se
`silver` ainda possui `partition_0` e seu índice automático. O layout atual não
usa partições: esses metadados antigos precisam ser removidos antes da validação,
preservando os arquivos no S3. Uma contagem zero com arquivos presentes pode indicar
esse problema de catálogo.

Para comparar os quatro indicadores HTTP com o CSV original, após o deploy:

```powershell
python tests/check_silver_metrics.py --base-url http://IP_DO_FRONTEND
```

O teste agrega a fonte independentemente do Athena e compara total, tecnologia,
senioridade e área. HTTP 200 sozinho não garante que o CSV foi interpretado corretamente.

Se a nova imagem falhar, o script tenta restaurar a imagem anterior validada usando
endereços/segredos atuais e ainda assim retorna falha para a implantação solicitada.
Uma configuração inválida também pode impedir o rollback: o fluxo não informa sucesso
nessa situação. Na primeira implantação não existe imagem anterior para restaurar.

**As telas React atuais ainda usam mocks.** Os testes verificam publicação dos arquivos
e caminho HTTP da API, não a substituição dos dados simulados nas telas.

## 8. Provisionar e implantar pelo n8n

O workflow executa a sequência completa: lê `application.yaml`, cria/atualiza a stack,
aguarda as EC2s e implanta banco → backend → frontend. Não exige `prepare`, `plan` ou
`apply` antes da execução, nem Docker/AWS CLI dentro do container n8n.

### Preparação

1. Configure `files/application.local.json` conforme a seção 3 e publique as imagens.
2. Garanta os exports da rede-base, NAT, instance profile e os parâmetros SecureString.
   A senha do banco é criada uma única vez conforme a seção 5. O workflow verifica
   os metadados dos parâmetros; os valores são buscados pelas próprias EC2s.
3. Com Athena habilitado, confirme a stack compute, o processamento Silver e o crawler.
4. Aplique a configuração do container:

   ```powershell
   docker compose up -d --build
   ```

   Os volumes usados são:

   | Origem | Caminho no n8n |
   |---|---|
   | `./files` | `/files` |
   | `./scripts` | `/files/scripts` (somente leitura) |
   | `../noctua-backend/database` | `/files/database` (somente leitura) |

   Se o backend estiver em outro local, defina `NOCTUA_SCHEMA_DIRECTORY` antes de
   executar o Compose. A pasta deve conter `script-noctua.sql`. O Code node precisa
   de `crypto,zlib`, já liberados por `NODE_FUNCTION_ALLOW_BUILTIN` no Compose.
5. Importe o JSON atualizado `application-n8n-noctua.json`.
6. Selecione a mesma credencial AWS em **CloudFormation API**, **SSM infrastructure API**,
   **Send SSM command** e **Get SSM status**. Use `us-east-1` e os três valores da sessão atual.
7. Execute **Start application deploy**.

### Sequência do workflow

1. Lê configuração, template, script remoto e schema pelos volumes. Valida os campos
   e empacota os fontes atuais em JSON comprimido, com checksum SHA-256.
2. Confere os exports da rede com paginação, os metadados dos segredos e os outputs
   `GlueDatabaseName`/`AthenaWorkGroupName` quando Athena está habilitado.
3. Valida o template no CloudFormation e consulta a stack de aplicação.
4. Cria um change set `CREATE` ou `UPDATE` e **executa automaticamente**. Nas atualizações,
   preserva parâmetros não gerenciados pelo JSON, como o tamanho do volume. Se não
   houver mudanças, remove apenas o change set vazio e reutiliza a stack.
5. Aguarda tanto a conclusão da stack quanto a execução do change set. Estados de
   rollback/falha interrompem o fluxo. O limite da operação da stack é 40 minutos.
6. Consulta os outputs atuais e aguarda as três EC2s `Online` no SSM, até 20 minutos.
7. Monta os comandos com os IDs/IPs atuais e implanta banco → backend → frontend.
   O script remoto também aguarda `/opt/noctua/bootstrap-ready` antes de implantar.

O workflow espera 10 segundos **entre consultas**, não como critério de sucesso.
Cada comando precisa retornar `Success` e código zero. O polling trata consistência
eventual, HTTP 429/5xx e throttling dentro do limite de 70 minutos por comando.
Credenciais inválidas, acesso negado, falhas de transporte e falhas remotas interrompem
a execução. O envio SSM e a criação/execução do change set não são repetidos automaticamente
após respostas ambíguas: confira o histórico AWS antes de reiniciar.

O nó **Deployment result** retorna `DEPLOY_VALIDATED` somente após validar as três
etapas. A saída inclui stack, região, `frontendUrl`, duração, `athenaValidated`,
`infrastructure.action` (`CREATE`, `UPDATE` ou `UNCHANGED`) e `components`, com os IDs
das instâncias/comandos, estados e saídas SSM. Os digests aparecem na saída remota.
Os logs estão sujeitos aos limites de tamanho do SSM. Esse resultado representa os
testes do deploy; a interface ainda pode apresentar dados simulados.

Execute somente um release por vez e não altere a stack durante a execução. Há lock
por instância, mas não uma transação distribuída entre workflows concorrentes. Se o
n8n parar, CloudFormation/SSM podem continuar: confira change set e CommandId antes
de repetir. A nova execução relê os arquivos e consulta os outputs novamente.

`application.py prepare` continua disponível para produzir o pedido do workflow legado;
esse arquivo não é consumido pelo fluxo atual. O deploy CLI continua disponível na seção 7.

### Erro `Converting circular structure to JSON`

No n8n 2.43.4, o HTTP Request com corpo `Raw` pode receber a resposta como um stream
`IncomingMessage`. Ao forçar a resposta para `Text`, o nó tenta serializar esse stream,
que contém referências circulares entre resposta, socket e requisição.

O workflow usa **Form URLencoded / Using Single Field** no **CloudFormation API**, com
header `Accept: application/xml`, resposta **Text**, campo de saída `body` e
**Include Response Headers and Status** ligado. O header é necessário porque o `Accept`
padrão do n8n prioriza JSON mesmo com resposta **Text**; sem ele, um retorno como
`{"ListExportsResponse": ...}` causa erro no nó **Parse CloudFormation XML**.
Os três nós SSM usam corpo **JSON / Using JSON**, header
`Content-Type: application/x-amz-json-1.1`, resposta **JSON** e inclusão do status ligada.
**Never Error** permanece ligado: os nós seguintes avaliam os códigos HTTP e os erros AWS.

Reimporte `application-n8n-noctua.json` e reassocie a credencial AWS aos quatro nós.
Alterar o arquivo no repositório não atualiza a cópia já importada no editor.

Para validar os nós HTTP reais sem acessar a AWS:

```powershell
python tests/check_application_workflow.py --http --scenario create
```

O teste usa um container descartável sem rede externa, servidor HTTP em loopback e
credenciais fictícias. Verifica assinatura AWS, respostas XML/JSON, HTTP 400/503 e o
fluxo até o resultado final. Também aceita `--scenario update` e `--scenario unchanged`.

## 9. HTTPS

HTTP é permitido para validação inicial com CIDR restrito. Antes de acesso público:

1. Aponte o domínio para o EIP mostrado em `FrontendPublicIp`.
2. Obtenha um certificado válido e a chave privada por seu processo de emissão.
3. Cadastre um `SecureString` SSM contendo:

```json
{"certificate_pem":"-----BEGIN CERTIFICATE-----\n...","private_key_pem":"-----BEGIN PRIVATE KEY-----\n..."}
```

4. Configure `tls_parameter` e `server_name` com o nome correspondente ao certificado.
5. Faça novo deploy; Nginx passa a redirecionar HTTP para HTTPS.
6. Depois, ajuste `frontend_ingress_cidr` se necessário e aplique o change set.

Os testes HTTPS usam o hostname real e validam o certificado, sem `--insecure`.
O SSM padrão tem limite de 4 KB; parâmetros Advanced chegam a 8 KB, sujeitos a
permissões/custos. Se o conjunto certificado/chave não couber, será necessário outro
armazenamento. Emissão e renovação automática de certificados não foram implementadas:
ao renovar, atualize o parâmetro e execute novo deploy antes do vencimento.

## 10. Retirar a EC2 antiga do banco

Após validar o novo ambiente, instale a dependência do parser e prepare a remoção:

```powershell
python -m pip install -r scripts/requirements.txt
python scripts/application.py retire-database-plan
```

O comando revalida frontend/backend e seus registros de versão/endereço, lê o template
**atualmente implantado** de `compute-stack`, remove apenas `EC2Database` e cria um
change set. Exige que a única mudança seja a remoção desse recurso; caso contrário,
descarta o plano. Não depende de o template local refletir todas as alterações AWS.

Revise a identificação da instância antiga e aplique o ARN retornado:

```powershell
python scripts/application.py apply --change-set ARN_DA_REMOCAO
```

A instância antiga foi declarada como não utilizada. Não há migração automática dos
seus dados. Nenhum comando de retirada é chamado durante o deploy normal.

## 11. Backup, restauração e próximas releases

Há backup consistente inicial e diário às 03:00 UTC, via `noctua-backup.timer`, para
o bucket retornado em `DatabaseBackupBucket`. Inclui `NOCTUA` e o registro de baseline;
contas MySQL não são incluídas. O bucket possui retenção de objetos por 30 dias.

Diagnóstico na EC2 banco via Session Manager:

```bash
sudo systemctl status noctua-backup.timer
sudo journalctl -u noctua-backup.service --no-pager
sudo systemctl start noctua-backup.service
```

Para testar restauração, use uma instância/base isolada: baixe o `.sql.gz` do S3,
descomprima e importe com o administrador MySQL; recrie o usuário e valide contagens.
Um dump pode substituir tabelas existentes. A restauração não é executada pelo deploy
e ainda exige ensaio no ambiente real.

O volume e bucket têm `DeletionPolicy/UpdateReplacePolicy: Retain`. Excluir a stack
deixa esses recursos retidos, com seus custos. Substituir a EC2 pode criar um novo
volume: o antigo permanece retido, mas não é reconectado automaticamente. Faça backup
e planeje recuperação antes de aprovar substituições. Retenção não é alta disponibilidade.

Nova release de código:

1. Publicar com outra tag pelo `publish_images.py`.
2. Atualizar os dois digests na configuração local (manter o digest do componente que não mudou).
3. Executar `deploy` via CLI ou executar novamente o workflow n8n atualizado.

Voltar uma versão: informe o digest anterior e execute novamente, verificando
compatibilidade com o schema atual. A senha e os IPs são resolvidos novamente.

## 12. Verificações locais e aceite AWS

Na raiz da infraestrutura, com Python, PyYAML e Node disponíveis:

```powershell
python -m unittest discover -s tests -v
python tests/check_application_workflow.py --scenario create
python tests/check_application_workflow.py --scenario update
python tests/check_application_workflow.py --scenario unchanged
python tests/check_frontend_image.py noctua-frontend:automation-check
```

Os testes cobrem contrato de configuração, integridade do pacote, escopo da retirada,
rollback, propagação de falha Athena e estados do polling n8n. Use `cfn-lint` para
validar `files/application.yaml` e construa a imagem frontend com Docker.

Evidências locais de 23/10/2026:

- 12 testes automatizados aprovados.
- `cfn-lint` 1.58.0: novo template aprovado em `us-east-1`.
- Build Docker do frontend aprovado com instalação limpa e artefato DOCX incluído.
- Teste com containers descartáveis aprovado: HTML, rotas SPA, DOCX, health, preservação
  do prefixo `/api/` e erro propagado quando o upstream fica indisponível.
- Workflow importado com sucesso em container descartável n8n 2.43.4. Os testes de
  código verificam polling; a execução dos nós autenticados contra AWS ainda é pendente.

Verificação local da recriação do workflow em 26/10/2026:

- 25 testes da suíte aprovados, incluindo entrada gerada pelo produtor atual, erros
  HTTP/SSM, expiração, timeout e simulação das três etapas com preservação dos resultados.
- Importação aprovada em container descartável com a imagem local
  `noctua-infraestructure-n8n`, sem rede. A execução autenticada contra AWS segue pendente.

Verificação da revisão stack + deploy:

- 36 testes da suíte aprovados, incluindo paginação SSM, preservação dos bytes do
  schema no desempacotamento e tratamento de respostas HTTP transitórias antes do XML.
- Execução offline em containers descartáveis n8n aprovada nos cenários `create`,
  `update` e `unchanged`, com respostas AWS simuladas e rede desabilitada.
- A execução verifica leitura dos volumes, módulos `crypto/zlib`, parsing XML,
  preservação do status HTTP, loops e associação dos itens até o resultado final.
- `cfn-lint` 1.58.0 aprovou `files/application.yaml` em `us-east-1`.
- `docker compose config --quiet` aprovado.
- Não houve execução autenticada ou provisionamento na AWS nesta revisão.

Aceites que precisam do laboratório real:

- Stacks criadas e EC2s Online no SSM.
- Baseline, usuário e backup inicial aprovados.
- Oito endpoints comparados às fontes reais.
- Frontend e proxy acessíveis pelo caminho público esperado.
- Reinício das instâncias, segunda release e rollback testados.
- Restauração de backup ensaiada.
- Workflow importado e executado com a versão instalada do n8n.
- Remoção da instância antiga confirmada pelo change set.
