#!/usr/bin/env python3
"""
Debug específico para o problema de JSON não encontrado.
"""

import os
import glob
from pathlib import Path

# Caminho exato do usuário
CAMINHO_JSON = r"C:\Users\Lucas Bianco\Desktop\Projetos Dev\Promos\dist-interface\ofertas_relampago\Historico de anuncios"

print("=" * 80)
print("🔍 DEBUG: Problema com JSON não encontrado")
print("=" * 80)

print(f"\n📁 Caminho informado pelo usuário:")
print(f"   {CAMINHO_JSON}")

print(f"\n✓ Caminho existe? {os.path.exists(CAMINHO_JSON)}")

if os.path.exists(CAMINHO_JSON):
    print(f"\n📂 Conteúdo da pasta:")
    try:
        arquivos = os.listdir(CAMINHO_JSON)
        print(f"   Total de arquivos: {len(arquivos)}")
        
        for idx, arq in enumerate(arquivos, 1):
            caminho_completo = os.path.join(CAMINHO_JSON, arq)
            eh_json = arq.endswith('.json')
            eh_ofertas = 'ofertas_' in arq
            tipo = "📄 JSON" if arq.endswith('.json') else "📋"
            print(f"   {idx}. {tipo} {arq}")
            if arq.endswith('.json'):
                tamanho = os.path.getsize(caminho_completo)
                print(f"      └─ Tamanho: {tamanho} bytes")
    except Exception as e:
        print(f"   ❌ Erro ao listar: {e}")
    
    print(f"\n🔎 Teste do glob pattern:")
    
    # Teste 1: Pattern simples
    pattern1 = os.path.join(CAMINHO_JSON, "*.json")
    resultado1 = glob.glob(pattern1)
    print(f"   Pattern: {pattern1}")
    print(f"   Encontrados: {len(resultado1)}")
    if resultado1:
        for r in resultado1[:3]:
            print(f"     • {os.path.basename(r)}")
    
    # Teste 2: Pattern com ofertas_
    pattern2 = os.path.join(CAMINHO_JSON, "ofertas_*.json")
    resultado2 = glob.glob(pattern2)
    print(f"\n   Pattern: {pattern2}")
    print(f"   Encontrados: {len(resultado2)}")
    if resultado2:
        for r in resultado2[:3]:
            print(f"     • {os.path.basename(r)}")
    
    # Teste 3: Verificar com Path
    print(f"\n🔎 Teste com pathlib.Path:")
    p = Path(CAMINHO_JSON)
    jsons_path = list(p.glob("ofertas_*.json"))
    print(f"   Path.glob('ofertas_*.json'): {len(jsons_path)}")
    if jsons_path:
        for jp in jsons_path[:3]:
            print(f"     • {jp.name}")

else:
    print(f"\n❌ Caminho NÃO existe!")
    print(f"\n💡 Verificando pasta pai...")
    pasta_pai = os.path.dirname(CAMINHO_JSON)
    print(f"   Pasta pai: {pasta_pai}")
    print(f"   Existe? {os.path.exists(pasta_pai)}")
    
    if os.path.exists(pasta_pai):
        print(f"   Conteúdo:")
        for item in os.listdir(pasta_pai):
            print(f"     • {item}")

print("\n" + "=" * 80)
print("📝 RESUMO:")
print("=" * 80)

if os.path.exists(CAMINHO_JSON):
    arquivos = os.listdir(CAMINHO_JSON)
    jsons = [a for a in arquivos if a.endswith('.json')]
    ofertas_jsons = [a for a in arquivos if a.startswith('ofertas_') and a.endswith('.json')]
    
    print(f"✓ Pasta existe: SIM")
    print(f"✓ Total de arquivos: {len(arquivos)}")
    print(f"✓ Arquivos .json: {len(jsons)}")
    print(f"✓ Arquivos ofertas_*.json: {len(ofertas_jsons)}")
    
    if ofertas_jsons:
        print(f"\n✅ JSONs encontrados!")
        print("   Se a GUI ainda não encontra, o problema pode ser:")
        print("   1. Constante PASTA_RELAMPAGO_HISTORICO diferente")
        print("   2. Caracteres especiais no caminho")
        print("   3. Problema na função listar_jsons_ofertas()")
    else:
        print(f"\n❌ Nenhum arquivo 'ofertas_*.json' encontrado!")
        if jsons:
            print(f"   Mas existem {len(jsons)} arquivos .json:")
            for j in jsons[:3]:
                print(f"     • {j}")
else:
    print(f"❌ Pasta NÃO existe: {CAMINHO_JSON}")

print("\n" + "=" * 80)
