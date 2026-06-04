
# Melhorias

- Normalizar a forma de busca, os marcadores HTML mudam muito de um para o outro. Passar condições da tela (Deve conter texto especifico, Nao pode conter texto especifico)
- Aceitar link em todas as configurações. O Link tem prioridade de busca.

- Executar monitoramento em segundo plano mesmo com app fechado

- Ampliar extratores de preço por marketplace para maior precisão
- Refinar as buscas on demand para simular os filtros dos sites: na seleção de marketplace, remover "Todas". Se eu selecionar mercado livre, habilitar os filtros do mercado livre para reproduzir durante a consulta. O mesmo deve ser feito com os outros marketplaces, baseado nos filtros de cada uma deles. Mercado livre já possui ID nas categorias. Documentar os IDs das subcategorias e fazer um DePara para deixar a validação mais robusta.

- Criar uma busca genérica no Google. Extrair os marcadores de filtro do Google da aba shopping para conseguir o anúncio mais barato de cada marketplace e fazer uma varredura rápida on demand.
- Configurar alerta de preço para olhar no Google como alternativa caso nenhum dos links informados na configuração tenha redução de preço
- A configuração de campanha deve aceitar links, até 5

- Refinar o alerta de preço: Depois de extrair o preço atual do link, realizar uma busca no site pela descrição da configuração. Recuperar todos os produtos encontrados em que a faixa de preço variar 20%. A ideia é que além de pesquisar o link específico, busque por novos anúncios que possam ter sido criados e eventualmente estejam mais baratos


# Bugs and Fixes

