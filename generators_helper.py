"""Helper para integrar geração de posts Instagram no fluxo de saídas.

Facilita a chamada da geração de posts após executar buscas.
"""

import os
import glob
from pathlib import Path
from typing import Optional, List

try:
    from generators.instagram_post_generator import gerar_posts_em_lote
    GERADORES_DISPONIVEL = True
except ImportError:
    GERADORES_DISPONIVEL = False


def gerar_posts_instagram_para_json_recente(
    pasta_json: str,
    formatos: List[str] = ["feed", "story"],
    pasta_saida: Optional[str] = None,
    duracao_video_segundos: int = 10,
) -> bool:
    """Procura o JSON mais recente em uma pasta e gera posts Instagram.
    
    Args:
        pasta_json: Pasta onde estão os JSONs gerados (ex: dist-interface/ofertas_relampago/Historico de anuncios)
        formatos: Formatos a gerar ['feed', 'story', 'video'] ou combinacoes
        pasta_saida: Pasta de saída (padrão: dist-interface/instagram_posts)
        duracao_video_segundos: Duracao do video em segundos (entre 8 e 15)
    
    Returns:
        True se sucesso, False se falha ou sem JSONs encontrados
    """
    if not GERADORES_DISPONIVEL:
        print("⚠️ Módulo generators não disponível")
        return False
    
    if not os.path.exists(pasta_json):
        print(f"❌ Pasta não encontrada: {pasta_json}")
        return False
    
    # Encontrar JSONs mais recentes
    jsons = glob.glob(os.path.join(pasta_json, "ofertas_*.json"))
    
    if not jsons:
        print(f"⚠️ Nenhum arquivo JSON encontrado em: {pasta_json}")
        return False
    
    # Ordenar por data de modificação (mais recente primeiro)
    jsons.sort(key=os.path.getmtime, reverse=True)
    json_mais_recente = jsons[0]
    
    print(f"\n📸 Gerando posts Instagram do arquivo mais recente:")
    print(f"   {os.path.basename(json_mais_recente)}")
    
    try:
        gerar_posts_em_lote(
            json_mais_recente,
            formatos=formatos,
            pasta_saida=pasta_saida,
            duracao_video_segundos=duracao_video_segundos,
        )
        return True
    except Exception as e:
        print(f"❌ Erro ao gerar posts: {e}")
        return False


def listar_jsons_ofertas(pasta_json: str) -> List[str]:
    """Lista todos os JSONs de ofertas em uma pasta.
    
    Args:
        pasta_json: Pasta com JSONs
    
    Returns:
        Lista de caminhos de JSONs, ordenados por data (mais recente primeiro)
    """
    if not os.path.exists(pasta_json):
        return []
    
    jsons = glob.glob(os.path.join(pasta_json, "ofertas_*.json"))
    jsons.sort(key=os.path.getmtime, reverse=True)
    
    return jsons


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Uso: python generators_helper.py <pasta_json> [feed|story|video|ambos] [duracao_video_segundos]")
        sys.exit(1)
    
    pasta = sys.argv[1]
    formatos = ['feed', 'story']
    duracao_video = 10
    
    if len(sys.argv) > 2:
        arg = sys.argv[2].lower()
        if arg == 'feed':
            formatos = ['feed']
        elif arg == 'story':
            formatos = ['story']
        elif arg == 'video':
            formatos = ['video']

    if len(sys.argv) > 3:
        try:
            duracao_video = int(sys.argv[3])
        except ValueError:
            print("⚠️ Duração inválida, usando 10 segundos.")
    
    sucesso = gerar_posts_instagram_para_json_recente(
        pasta,
        formatos=formatos,
        duracao_video_segundos=duracao_video,
    )
    sys.exit(0 if sucesso else 1)
