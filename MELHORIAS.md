
# Melhorias

- Normalizar a forma de busca, os marcadores HTML mudam muito de um para o outro. Passar condições da tela (Deve conter texto especifico, Nao pode conter texto especifico)
- Aceitar link em todas as configurações. O Link tem prioridade de busca.
- Impedir que a categoria seja informada na caixa de texto da busca (Exemplo, texto inputado em uma das execuções: 'raqueteira c esportes e fitness')
- Executar monitoramento em segundo plano mesmo com app fechado
- Permitir editar/remover/pausar alertas na interface
- Ampliar extratores de preço por marketplace para maior precisão
- Refinar as buscas on demand para simular os filtros dos sites: na seleção de marketplace, remover "Todas". Se eu selecionar mercado livre, habilitar os filtros do mercado livre para reproduzir durante a consulta. O mesmo deve ser feito com os outros marketplaces, baseado nos filtros de cada uma deles. Mercado livre já possui ID nas categorias. Documentar os IDs das subcategorias e fazer um DePara para deixar a validação mais robusta.
- Gerar job de atualização diária do DePara de categorias chamando a API pública do ML: https://api.mercadolibre.com/sites/MLB/categories/all
- Criar uma busca genérica no Google. Extrair os marcadores de filtro do Google da aba shopping para conseguir o anúncio mais barato de cada marketplace e fazer uma varredura rápida on demand.
- Configurar alerta de preço para olhar no Google como alternativa caso nenhum dos links informados na configuração tenha redução de preço
- A configuração de campanha deve aceitar links, até 5


# Bugs and Fixes

- Informativo com resumo de falhas de execução do GRID deve ser linha a linha
- A linha deve ser destacada em vermelho quando houver falha de execução apenas, disparo não realizado por não se encaixar nos critérios não é falha
- O modo relâmpago on demand deve permitir uma descrição. Quando houver descrição, ela deve ser inserida na busca antes de extrair e percorrer o HTML da página. A prioridade é Categoria, depois descrição e só depois procura preço e desconto.
- O modo busca padrão on demand também deve permitir uma descrição. Quando houver descrição, ela deve ser inserida na busca antes de extrair e percorrer o HTML da página. A prioridade é Categoria, depois descrição e só depois procura preço e desconto.
- Refinar o alerta de preço: Depois de extrair o preço atual do link, realizar uma busca no site pela descrição da configuração. Recuperar todos os produtos encontrados em que a faixa de preço variar 20%. A ideia é que além de pesquisar o link específico, busque por novos anúncios que possam ter sido criados e eventualmente estejam mais baratos
- Modo On Demand de busca normal não está pegando o preço no lugar certo. Ele encontra o preço correto na lista de anúncios e salva o HTML, mas dentro do link do anúncio, o valor lido é o antigo. Por isso não é gerado saída pra ele.
- As configurações salvas da planilha ainda não estão sendo convertidas para meu número de telefone, apesar de ser um paliativo, é importante para que receba aviso dos alertas
 