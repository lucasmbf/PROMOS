#!/usr/bin/env python3
"""
Diagnóstico para problema com geração de posts Instagram.

PROBLEMA CORRIGIDO: 
- JSONs agora são SEMPRE salvos em 'dist-interface/ofertas_relampago/Historico de anuncios'
- Mesmo se você escolher uma pasta personalizada durante a busca
- A GUI encontrará o JSON imediatamente após a busca

Executar com: python diagnostico_instagram.py
"""

import os
import json
import glob
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BASE_SAIDA = BASE_DIR / "dist-interface"

# Pastas esperadas
PASTA_RELAMPAGO_HISTORICO = str(BASE_SAIDA / "ofertas_relampago" / "Historico de anuncios")
PASTA_SAIDA_ALERTA = str(BASE_SAIDA / "saidas_execucoes" / "Alerta")
PASTA_SAIDA_CAMPANHA = str(BASE_SAIDA / "saidas_execucoes" / "Campanha")
PASTA_SAIDA_ONDEMAND = str(BASE_SAIDA / "saidas_execucoes" / "OnDemand")

print("=" * 70)
print("🔍 DIAGNÓSTICO: Gerador de Posts Instagram")
print("=" * 70)

print("\n📁 Estrutura de Pastas:\n")

pastas = {
    "Relâmpago (PRINCIPAL)": PASTA_RELAMPAGO_HISTORICO,
    "Alerta": PASTA_SAIDA_ALERTA,
    "Campanha": PASTA_SAIDA_CAMPANHA,
    "OnDemand": PASTA_SAIDA_ONDEMAND,
}

total_jsons_encontrados = 0

for nome, caminho in pastas.items():
    existe = os.path.exists(caminho)
    status = "✅ Existe" if existe else "⚠️  Será criada"
    print(f"  {nome:20} {status}")
    print(f"    Caminho: {caminho}")
    
    if existe:
        # Listar JSONs
        jsons = glob.glob(os.path.join(caminho, "ofertas_*.json"))
        if jsons:
            print(f"    📄 JSONs encontrados: {len(jsons)}")
            total_jsons_encontrados += len(jsons)
            # Mostrar os 3 mais recentes
            jsons.sort(key=os.path.getmtime, reverse=True)
            for json_file in jsons[:3]:
                nome_arquivo = os.path.basename(json_file)
                tamanho = os.path.getsize(json_file)
                print(f"       • {nome_arquivo} ({tamanho} bytes)")
                
                # Tenta ler e validar JSON
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        dados = json.load(f)
                    total_ofertas = dados.get('total', 0)
                    print(f"         └─ ✅ Válido ({total_ofertas} ofertas)")
                except Exception as e:
                    print(f"         └─ ❌ Erro: {e}")
        else:
            print(f"    ℹ️  Nenhum JSON encontrado (normal se nunca executou busca)")
    print()

print("\n" + "=" * 70)
print("✅ FLUXO CORRETO (Agora Corrigido):")
print("=" * 70)
print("""
1. ✅ Clique em "BUSCAR OFERTAS RELÂMPAGO"
2. ✅ Escolha uma pasta personalizada (ou cancele para usar padrão)
3. ✅ Aguarde até ver mensagem "✅ ... posts relâmpago..."
   → JSON agora é salvo AUTOMATICAMENTE em:
     dist-interface/ofertas_relampago/Historico de anuncios/
4. ✅ Clique em "📸 GERAR POSTS INSTAGRAM"
5. ✅ Selecione o formato (Feed/Story/Ambos)
6. ✅ Posts são gerados na pasta de saída

ANTES: Os JSONs ficavam na pasta que você escolhia (❌ GUI não encontrava)
AGORA: JSONs são salvos TAMBÉM no histórico padrão (✅ GUI encontra sempre)
""")

print("\n" + "=" * 70)
print("📊 Resumo:")
print("=" * 70)
print(f"Total de JSONs encontrados: {total_jsons_encontrados}")
if total_jsons_encontrados > 0:
    print("✅ Tudo pronto! Execute uma busca e gere posts.")
else:
    print("ℹ️  Nenhum JSON encontrado ainda (normal na primeira execução)")
    
print("\n" + "=" * 70)

