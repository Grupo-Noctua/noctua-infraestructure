# noctua-infraestructure

Infraestrutura Noctua em CloudFormation e automação n8n.

## Aplicação: MySQL, backend e frontend

A camada de aplicação usa frontends em **ASG + ALB**, EC2s backend/MySQL, imagens no **Docker Hub**, deploy via **SSM** e
credenciais da **role das instâncias**. A sessão temporária do AWS Academy é
necessária para as operações de implantação no computador/n8n local.

Consulte o [passo a passo de implantação](docs/IMPLANTACAO_APLICACAO.md).
Para distinguir visualmente os nós, consulte [frontends A/B no load balancer](docs/FRONTENDS_LOAD_BALANCER.md).
O parâmetro opcional `frontend_image_b` permite distribuir uma segunda imagem entre os frontends.

- `files/application.yaml`: nova stack de aplicação.
- `files/application.example.json`: configuração de referência; copie para `files/application.local.json` e preencha os valores locais.
- `scripts/application.py`: provisionamento, deploy e retirada controlada do banco antigo.
- `scripts/publish_images.py`: build/testes e publicação no Docker Hub.
- `application-n8n-noctua.json`: provisiona/atualiza a stack de aplicação e depois faz o deploy via SSM.

O Compose monta `files` em `/files`, os scripts em `/files/scripts` e o schema do
backend em `/files/database`. O workflow lê os arquivos atuais diretamente; não
precisa executar `prepare`, `plan` ou `apply` antes dele.

Para executar:

1. Preencha `files/application.local.json`, incluindo os digests das imagens publicadas.
2. Garanta a rede-base, a saída NAT, o instance profile e os parâmetros SecureString.
3. Execute `docker compose up -d --build` para aplicar os volumes e as permissões do Code node.
4. Importe `application-n8n-noctua.json` e selecione a mesma credencial AWS temporária
   nos nós **CloudFormation and Auto Scaling API**, **SSM infrastructure API**, **Send SSM command** e **Get SSM status**.
5. Execute **Start application deploy**. O workflow aplica o change set automaticamente,
   aguarda CloudFormation, descobre os frontends do Auto Scaling Group, aguarda todas
    as instâncias no SSM e implanta banco → backend → assets em todos os frontends → cada frontend.

Com Athena habilitado, o processamento Silver e o crawler devem ter concluído antes
do deploy. A saída `DEPLOY_VALIDATED` inclui a URL e o resultado de cada componente.

O template `compute.yaml` passa a deixar o MySQL sob responsabilidade da stack de
aplicação. Em ambientes existentes, a remoção da EC2 antiga precisa do change set
descrito no guia; editar o arquivo local não altera a AWS.
