# Correção de cache e assets do frontend

Release: `elersonalves/noctua-frontend:release-20261102-dashboard-03`.

Digest: `sha256:c5b532f2f102b9ce23c0cf97322cd6ab0c0a30714eba4b23078987e27ddd7a3c`.

## Causa

HTML de uma versão anterior referenciava arquivos JavaScript que já não existiam
no container atualizado. O fallback SPA do Nginx retornava `index.html` com HTTP
200 e MIME `text/html` para esses arquivos, impedindo o carregamento dos módulos.

## Configuração aplicada

- HTML e rotas SPA: `Cache-Control: no-store`.
- `/assets/`: arquivos estáticos com cache imutável; arquivos ausentes retornam 404.
- Assets de releases anteriores ficam em `/opt/noctua/frontend-assets`, montado
  somente para leitura no container. Na migração, as imagens frontend disponíveis
  em cada EC2 fornecem os assets históricos.
- Arquivos com o mesmo nome e conteúdo são preservados sem reescrita. Uma colisão
  de conteúdo no mesmo nome interrompe a preparação.
- O driver CLI prepara os assets em todas as instâncias antes de publicar o novo
  HTML. O procedimento via SSM usado nesta release também executou essas duas fases.
- O smoke test verifica o MIME do JavaScript referenciado pelo HTML, além da API.

## Evidências

As duas instâncias ficaram saudáveis no balanceador. Foram validados os bundles
`index-D7mMpfqh.js`, `index-gIfLu13t.js` e `index-B_evEmhM.js`, seus CSSs e o
carregamento no Edge com HTML antigo simulado. A versão atual também passou na
navegação completa, comparando dados da interface aos oito endpoints reais.

Testes locais: 43 testes unitários de infraestrutura (42 da suíte e o novo teste
de ordenação executado separadamente), mais `tests/check_frontend_image.py` com
o container real, MIME/cache, arquivo ausente, rotas SPA e proxy da API.
