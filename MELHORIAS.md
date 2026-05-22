# Melhorias Pendentes

## Backlog informado pelo usuario

- Criar uma interface com um botao para cada funcao.
- Ao selecionar a funcao, abrir uma caixa com os parametros possiveis.
- Criar alertas de preco com varredura por descricao do produto no Mercado Livre.
- Permitir informar manualmente um valor alvo e avisar quando o preco ficar menor que esse valor.
- Criar uma sessao de agendamentos para automatizar execucoes por configuracao do usuario.
- Permitir criar configuracoes com categoria, descricao/produto, faixa de preco, desconto e marketplaces.
- Permitir definir intervalo de execucao da rotina automatica e forma de entrega das ofertas (arquivo unico, envio via WhatsApp etc.).
- Permitir editar, remover, pausar e reativar configuracoes de agendamento.

## Status

- Interface desktop criada em `gui_promos.py` com dois quadros:
	- Procurar produto
	- Procurar ofertas relampago
- Script de build da interface criado em `gerar_executavel_interface.ps1`.
- Executavel gerado em `dist-interface/promos_interface.exe`.
- Fluxo de buscar produto por HTML salvo do hub implementado e acionado pelo botao da interface.
- Botao `ALERTA DE PRECO` implementado com configuracao:
	- modo por URL (recomendavel) com uma ou mais URLs
	- modo por descricao e atributos
	- preco alvo
	- agendamento em horas (minimo 1 hora)
- Rotina de verificacao agendada implementada na interface (enquanto o app estiver aberto), com notificacao quando preco <= alvo.
- Pendencias do modulo de alertas/agendamentos:
	- executar monitoramento em segundo plano mesmo com app fechado
	- permitir editar/remover/pausar alertas na interface
	- ampliar extratores de preco por marketplace para maior precisao
